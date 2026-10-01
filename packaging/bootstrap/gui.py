"""Small native installation UI; no downloaded GUI framework or network."""
import os
import shutil
import subprocess
import threading
import time


def message(title, text, error=False):
    if os.name == 'nt':
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10 if error else 0x40)
    elif shutil.which('zenity'):
        subprocess.run(['zenity', '--error' if error else '--info', '--title='+title, '--text='+text], check=False)
    else:
        print(title + ': ' + text)


def installer_ui(work, launch, target):
    if os.name == 'nt':
        return windows_wizard(work, launch, target)
    if not shutil.which('zenity'):
        raise RuntimeError('Per l’installazione grafica su Linux serve Zenity. Chiedi a chi ti ha fornito Wiki22 di aiutarti a installarlo.')
    note = ('Wiki22\nLa tua enciclopedia, anche senza Internet.\n\n'
            'Wikipedia italiana è già inclusa.\nCreerò un’icona nelle applicazioni e sul desktop.\n'
            'Non servono account o Python da installare.\n\n'
            'Spazio necessario: circa 6,4 GB.\nDestinazione personale:\n' + str(target))
    if subprocess.run(['zenity', '--question', '--no-markup', '--title=Installa Wiki22',
                       '--width=490', '--ok-label=Installa', '--cancel-label=Annulla', '--text='+note]).returncode:
        return
    dialog = subprocess.Popen(['zenity', '--progress', '--title=Installazione Wiki22', '--width=490',
                               '--text=Preparazione…', '--percentage=0', '--auto-close'],
                              stdin=subprocess.PIPE, text=True)
    previous = [-1, '']
    def progress(percent, text):
        if dialog.poll() is not None:
            raise RuntimeError('Installazione annullata. Nessun dato personale è stato modificato.')
        percent = min(99, int(percent))
        if previous != [percent, text]:
            dialog.stdin.write(f'{percent}\n# {text}\n')
            dialog.stdin.flush()
            previous[:] = [percent, text]
    try:
        work(progress)
        dialog.stdin.write('100\n')
        dialog.stdin.close()
        dialog.wait(timeout=10)
    finally:
        if dialog.poll() is None:
            dialog.terminate()
    if subprocess.run(['zenity', '--question', '--title=Wiki22 è pronto', '--width=450',
                       '--ok-label=Apri Wiki22', '--cancel-label=Chiudi',
                       '--text=Da ora apri Wiki22 dall’icona nelle applicazioni.\nPuoi conservare questo programma di installazione per condividerlo.']).returncode == 0:
        launch()


def windows_wizard(work, launch, target):
    import ctypes as c
    from ctypes import wintypes as w
    u, k = c.WinDLL('user32', use_last_error=True), c.WinDLL('kernel32', use_last_error=True)
    LRESULT = c.c_ssize_t
    CALLBACK = c.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
    class WC(c.Structure):
        _fields_ = [('style', w.UINT), ('proc', CALLBACK), ('cbClsExtra', c.c_int), ('cbWndExtra', c.c_int),
                    ('instance', w.HINSTANCE), ('icon', w.HICON), ('cursor', w.HANDLE), ('background', w.HBRUSH),
                    ('menu', w.LPCWSTR), ('name', w.LPCWSTR)]
    u.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]; u.DefWindowProcW.restype = LRESULT
    u.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, c.c_int, c.c_int, c.c_int, c.c_int,
                                 w.HWND, w.HMENU, w.HINSTANCE, c.c_void_p]; u.CreateWindowExW.restype = w.HWND
    u.SendMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]; u.SendMessageW.restype = LRESULT
    u.SetWindowTextW.argtypes = [w.HWND, w.LPCWSTR]
    u.DestroyWindow.argtypes = [w.HWND]
    u.EnableWindow.argtypes = [w.HWND, w.BOOL]
    u.GetMessageW.argtypes = [c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT]
    u.TranslateMessage.argtypes = [c.POINTER(w.MSG)]
    u.DispatchMessageW.argtypes = [c.POINTER(w.MSG)]; u.DispatchMessageW.restype = LRESULT
    u.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    k.GetModuleHandleW.argtypes = [w.LPCWSTR]; k.GetModuleHandleW.restype = w.HMODULE
    instance = k.GetModuleHandleW(None)
    state = {'phase': 'ready', 'cancel': False, 'percent': 0, 'text': '', 'error': None}
    controls = {}
    def progress(p, text):
        if state['cancel']:
            raise RuntimeError('Installazione annullata. Nessun dato personale è stato modificato.')
        if int(p) != state['percent'] or text != state['text']:
            state.update(percent=int(p), text=text)
            u.PostMessageW(controls['window'], 0x8001, 0, 0)
    def worker():
        try:
            work(progress)
        except Exception as e:
            state['error'] = str(e)
        u.PostMessageW(controls['window'], 0x8002, 0, 0)
    @CALLBACK
    def proc(hwnd, msg, wp, lp):
        if msg == 0x111 and (wp & 0xffff) == 1:
            if state['phase'] == 'ready':
                state['phase'] = 'working'
                u.EnableWindow(controls['button'], False)
                u.SetWindowTextW(controls['button'], 'Installazione…')
                threading.Thread(target=worker).start()
            elif state['phase'] == 'done':
                launch()
                u.DestroyWindow(hwnd)
            else:
                u.DestroyWindow(hwnd)
            return 0
        if msg == 0x8001:
            u.SetWindowTextW(controls['text'], state['text'])
            u.SendMessageW(controls['bar'], 0x402, state['percent'], 0)
            return 0
        if msg == 0x8002:
            state['phase'] = 'error' if state['error'] else 'done'
            u.SetWindowTextW(controls['text'], state['error'] or 'Wiki22 è pronto.\nDa ora aprilo dall’icona sul desktop o nel menu Start.')
            u.SetWindowTextW(controls['button'], 'Chiudi' if state['error'] else 'Apri Wiki22')
            u.EnableWindow(controls['button'], True)
            if state['cancel']:
                u.DestroyWindow(hwnd)
            return 0
        if msg == 0x10:
            if state['phase'] == 'working':
                state['cancel'] = True
                u.SetWindowTextW(controls['text'], 'Annullamento in corso…')
            else:
                u.DestroyWindow(hwnd)
            return 0
        if msg == 2:
            u.PostQuitMessage(0)
            return 0
        return u.DefWindowProcW(hwnd, msg, wp, lp)
    wc = WC(0, proc, 0, 0, instance, None, None, w.HBRUSH(6), None, 'Wiki22Installer')
    u.RegisterClassW(c.byref(wc))
    c.WinDLL('comctl32').InitCommonControls()
    hwnd = u.CreateWindowExW(0, wc.name, 'Wiki22 — Installazione', 0x10CA0000,
                              150, 150, 600, 385, None, None, instance, None)
    if not hwnd:
        raise c.WinError(c.get_last_error())
    controls['window'] = hwnd
    text = ('Wiki22 — la tua enciclopedia\n\nWikipedia italiana già inclusa. Nessun account richiesto.\n'
            'Creerò un’icona sul desktop e nel menu Start.\nSpazio necessario: circa 6,4 GB.\n\n' + str(target))
    controls['text'] = u.CreateWindowExW(0, 'STATIC', text, 0x50000000, 25, 24, 535, 220, hwnd, None, instance, None)
    controls['bar'] = u.CreateWindowExW(0, 'msctls_progress32', '', 0x50000000, 25, 255, 535, 20, hwnd, None, instance, None)
    controls['button'] = u.CreateWindowExW(0, 'BUTTON', 'Installa', 0x50010001, 390, 292, 170, 32, hwnd, w.HMENU(1), instance, None)
    gdi = c.WinDLL('gdi32'); gdi.GetStockObject.restype = w.HANDLE
    for control in controls.values():
        u.SendMessageW(control, 0x30, gdi.GetStockObject(17), 1)
    msg = w.MSG()
    while u.GetMessageW(c.byref(msg), None, 0, 0) > 0:
        u.TranslateMessage(c.byref(msg)); u.DispatchMessageW(c.byref(msg))
    if state['error']:
        raise RuntimeError(state['error'])
