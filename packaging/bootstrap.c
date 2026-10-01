/* Wiki22 native Windows entry: no shell, no elevation, Unicode paths. */
#define UNICODE
#define _UNICODE
#define COBJMACROS
#include <windows.h>
#include <shlobj.h>
#include <shobjidl.h>
#include <shellapi.h>
#include <stdio.h>
#include <wchar.h>
#ifdef INSTALLER
#include "resources.h"
#endif

static int fail(const wchar_t *text) {
    MessageBoxW(NULL, text, L"Wiki22", MB_OK|MB_ICONERROR); return 1;
}

/* Only replace links belonging to a stamped sibling Wiki22 installation. */
static int own_prior(const wchar_t *prior, const wchar_t *self) {
    wchar_t a[32768],b[32768],stamp[32768];
    wcscpy(a,prior); wcscpy(b,self);
    wchar_t *x=wcsrchr(a,L'\\'),*y=wcsrchr(b,L'\\');
    if(!x||!y||_wcsicmp(x,L"\\Wiki22.exe")||_wcsicmp(y,L"\\Wiki22.exe")) return 0;
    *x=0; *y=0;
    swprintf(stamp,32768,L"%ls\\INSTALLAZIONE.json",a);
    if(GetFileAttributesW(stamp)==INVALID_FILE_ATTRIBUTES) return 0;
    x=wcsrchr(a,L'\\'); y=wcsrchr(b,L'\\'); if(!x||!y)return 0;
    if(wcscmp(x,L"\\1.1")&&wcscmp(x,L"\\1.1.1")&&wcscmp(x,L"\\1.1.2")&&wcscmp(x,L"\\1.2.0")&&wcscmp(x,L"\\1.2.1")&&wcscmp(x,L"\\1.3.0")&&wcscmp(x,L"\\1.4.0")&&wcscmp(x,L"\\1.5.0")&&wcscmp(x,L"\\1.6.0")&&wcscmp(x,L"\\1.7.0")&&wcscmp(x,L"\\1.7.1")&&wcscmp(x,L"\\1.8.0")&&wcscmp(x,L"\\1.8.1")) return 0;
    *x=0;*y=0;return _wcsicmp(a,b)==0;
}

static int shortcut(const wchar_t *self, const GUID *folder) {
    PWSTR location=NULL;
    if (FAILED(SHGetKnownFolderPath(folder, KF_FLAG_CREATE, NULL, &location))) return 1;
    wchar_t path[32768]; swprintf(path,32768,L"%ls\\Wiki22 Enciclopedia.lnk",location); CoTaskMemFree(location);
    IShellLinkW *link=NULL;
    HRESULT hr=CoCreateInstance(&CLSID_ShellLink,NULL,CLSCTX_INPROC_SERVER,&IID_IShellLinkW,(void**)&link);
    if (FAILED(hr)) return 1;
    IPersistFile *persist=NULL;
    hr=IShellLinkW_QueryInterface(link,&IID_IPersistFile,(void**)&persist);
    if(SUCCEEDED(hr) && GetFileAttributesW(path)!=INVALID_FILE_ATTRIBUTES) {
        wchar_t prior[32768]={0};
        hr=IPersistFile_Load(persist,path,STGM_READ);
        if(SUCCEEDED(hr)) hr=IShellLinkW_GetPath(link,prior,32768,NULL,SLGP_RAWPATH);
        if(FAILED(hr)||(wcscmp(prior,self)!=0 && !own_prior(prior,self))) { IPersistFile_Release(persist); IShellLinkW_Release(link); return 1; }
    }
    if(SUCCEEDED(hr)) {
        IShellLinkW_SetPath(link,self);
        IShellLinkW_SetDescription(link,L"Wiki22 — la tua enciclopedia locale");
        IShellLinkW_SetIconLocation(link,self,0);
        hr=IPersistFile_Save(persist,path,TRUE);
    }
    if(persist) IPersistFile_Release(persist);
    IShellLinkW_Release(link);
    return FAILED(hr);
}

int WINAPI wWinMain(HINSTANCE h,HINSTANCE previous,LPWSTR tail,int show) {
    wchar_t self[32768],base[32768],python[32768],command[32768];
    DWORD count=GetModuleFileNameW(NULL,self,32768);
    if(!count||count>=32768) return fail(L"Impossibile leggere il percorso dell’app.");
    wcscpy(base,self); wchar_t *slash=wcsrchr(base,L'\\'); if(!slash) return 1; *slash=0;
    if(wcscmp(tail,L"--shortcuts")==0) {
        CoInitialize(NULL);
        int result=shortcut(self,&FOLDERID_Desktop)|shortcut(self,&FOLDERID_Programs);
        CoUninitialize(); return result;
    }
#ifdef INSTALLER
    wchar_t temp[32768],guidstr[64]; GUID guid;
    if(!GetTempPathW(32768,temp)||FAILED(CoCreateGuid(&guid))) return 1;
    StringFromGUID2(&guid,guidstr,64);
    if(swprintf(base,32768,L"%lsWiki22-%ls",temp,guidstr)<0||!CreateDirectoryW(base,NULL)) return fail(L"Non riesco a preparare l’installazione nella cartella temporanea.");
    for(int i=0;i<BOOT_COUNT;i++) {
        HRSRC resource=FindResourceW(h,MAKEINTRESOURCEW(boot[i].id),RT_RCDATA);
        HGLOBAL loaded=LoadResource(h,resource); DWORD size=SizeofResource(h,resource),written=0;
        void *bytes=LockResource(loaded); wchar_t file[32768];
        swprintf(file,32768,L"%ls\\%ls",base,boot[i].name);
        HANDLE out=CreateFileW(file,GENERIC_WRITE,0,NULL,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,NULL);
        if(!resource||!bytes||out==INVALID_HANDLE_VALUE) return fail(L"Il programma di installazione è incompleto.");
        BOOL ok=WriteFile(out,bytes,size,&written,NULL); CloseHandle(out);
        if(!ok||written!=size) return fail(L"Spazio temporaneo insufficiente.");
    }
    swprintf(python,32768,L"%ls\\pythonw.exe",base);
    if(swprintf(command,32768,L"\"%ls\" -X utf8 -B \"%ls\\install.py\" --source \"%ls\" %ls",python,base,self,tail)<0) return 1;
#else
    swprintf(python,32768,L"%ls\\runtime\\python\\pythonw.exe",base);
    if(swprintf(command,32768,L"\"%ls\" -X utf8 -B \"%ls\\app_entry.py\" %ls",python,base,tail)<0) return 1;
#endif
    STARTUPINFOW si={0}; si.cb=sizeof(si); PROCESS_INFORMATION pi={0};
    if(!CreateProcessW(python,command,NULL,NULL,FALSE,CREATE_NO_WINDOW,NULL,base,&si,&pi)) return fail(L"Non riesco ad avviare Wiki22. Il programma potrebbe essere incompleto.");
    WaitForSingleObject(pi.hProcess,INFINITE); DWORD result=1; GetExitCodeProcess(pi.hProcess,&result);
    CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
#ifdef INSTALLER
    for(int i=0;i<BOOT_COUNT;i++) { wchar_t file[32768]; swprintf(file,32768,L"%ls\\%ls",base,boot[i].name); DeleteFileW(file); }
    RemoveDirectoryW(base);
#endif
    return (int)result;
}
