from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from wiki22.knowledge.library_registry import (
    LibraryRegistry,
)


class ScopeSelector(
    tk.Frame,
):

    def __init__(
        self,
        master,
        *,
        wiki22_root: str | Path,
    ) -> None:

        super().__init__(
            master,
            bg="#EAF1FF",
            highlightbackground="#CFDCFA",
            highlightthickness=1,
        )

        self.registry = LibraryRegistry(
            Path(
                wiki22_root
            ).resolve()
        )

        self.registry.ensure()

        self.choice = tk.StringVar()

        self.option_map = {}

        self.current_mode = None
        self.current_ids = []

        tk.Label(
            self,
            text="Conoscenza",
            bg="#EAF1FF",
            fg="#2563EB",
            font=(
                "DejaVu Sans",
                9,
                "bold",
            ),
        ).pack(
            side="left",
            padx=(12, 8),
            pady=9,
        )

        self.combo = ttk.Combobox(
            self,
            textvariable=self.choice,
            state="readonly",
            width=44,
        )

        self.combo.pack(
            side="left",
            fill="x",
            expand=True,
            padx=(0, 12),
            pady=7,
        )

        self.combo.bind(
            "<<ComboboxSelected>>",
            self.on_selected,
        )

        self.refresh()

    def _enabled(
        self,
    ):

        return [
            row
            for row in (
                self.registry
                .list_libraries()
            )
            if row.get(
                "enabled"
            ) is True
        ]

    def refresh(
        self,
    ) -> None:

        previous_mode = (
            self.current_mode
        )

        previous_ids = list(
            self.current_ids
        )

        rows = self._enabled()

        options = {}
        values = []

        default = (
            self.registry
            .default_library()
        )

        # ----------------------------------------------------
        # One SINGLE option per active library.
        # ----------------------------------------------------

        for row in rows:

            library_id = str(
                row["id"]
            )

            name = str(
                row.get(
                    "name",
                    library_id,
                )
            )

            label = (
                f"Singola · {name}"
            )

            if (
                default is not None
                and library_id
                == str(
                    default["id"]
                )
            ):
                label += "  (predefinita)"

            values.append(
                label
            )

            options[
                label
            ] = (
                "SINGLE",
                [library_id],
            )

        # ----------------------------------------------------
        # Unified
        # ----------------------------------------------------

        if rows:

            label = (
                f"Unificata · Tutte le librerie attive "
                f"({len(rows)})"
            )

            values.append(
                label
            )

            options[
                label
            ] = (
                "UNIFIED",
                [
                    str(
                        row["id"]
                    )
                    for row in rows
                ],
            )

        # ----------------------------------------------------
        # Custom
        # ----------------------------------------------------

        if len(rows) >= 2:

            values.append(
                "Personalizzata..."
            )

            options[
                "Personalizzata..."
            ] = (
                "CUSTOM_PICK",
                [],
            )

        if not rows:

            values = [
                (
                    "Nessuna libreria attiva "
                    "· importa o attiva una libreria"
                )
            ]

            options[
                values[0]
            ] = (
                None,
                [],
            )

        self.option_map = (
            options
        )

        self.combo[
            "values"
        ] = values

        # Preserve scope where possible.
        restored = False

        if (
            previous_mode
            in {
                "SINGLE",
                "UNIFIED",
                "CUSTOM",
            }
            and previous_ids
        ):

            active_ids = {
                str(
                    row["id"]
                )
                for row in rows
            }

            retained = [
                item
                for item in previous_ids
                if item in active_ids
            ]

            if retained:

                self.current_mode = (
                    previous_mode
                )

                self.current_ids = (
                    retained
                )

                if (
                    previous_mode
                    == "CUSTOM"
                ):

                    self._show_custom_label()

                    restored = True

                else:

                    for label, (
                        mode,
                        ids,
                    ) in options.items():

                        if (
                            mode
                            == previous_mode
                            and ids
                            == retained
                        ):
                            self.choice.set(
                                label
                            )

                            restored = True
                            break

        if previous_mode == "UNIFIED" and rows:
            for label, (mode, ids) in options.items():
                if mode == "UNIFIED":
                    self.current_mode, self.current_ids = mode, list(ids)
                    self.choice.set(label)
                    restored = True
                    break
        elif previous_mode in {"SINGLE", "CUSTOM"} and previous_ids:
            active_ids = {str(row["id"]) for row in rows}
            if any(item not in active_ids for item in previous_ids):
                self.current_mode, self.current_ids = previous_mode, previous_ids
                label = "Selezione non disponibile · scegli una libreria attiva"
                self.choice.set(label)
                restored = True

        if not restored:

            if rows:

                if default is not None:

                    default_id = str(
                        default["id"]
                    )

                    for label, (
                        mode,
                        ids,
                    ) in options.items():

                        if (
                            mode == "SINGLE"
                            and ids
                            == [
                                default_id
                            ]
                        ):
                            self.choice.set(
                                label
                            )

                            self.current_mode = (
                                "SINGLE"
                            )

                            self.current_ids = [
                                default_id
                            ]

                            restored = True
                            break

                if not restored:

                    first = values[0]

                    self.choice.set(
                        first
                    )

                    mode, ids = (
                        options[
                            first
                        ]
                    )

                    self.current_mode = (
                        mode
                    )

                    self.current_ids = (
                        list(ids)
                    )

            else:

                self.choice.set(
                    values[0]
                )

                self.current_mode = (
                    None
                )

                self.current_ids = []

    def on_selected(
        self,
        _event=None,
    ) -> None:

        label = self.choice.get()

        mode, ids = (
            self.option_map.get(
                label,
                (
                    None,
                    [],
                ),
            )
        )

        if mode == "CUSTOM_PICK":

            self._pick_custom()
            return

        self.current_mode = (
            mode
        )

        self.current_ids = (
            list(ids)
        )

    def _pick_custom(
        self,
    ) -> None:

        rows = self._enabled()

        window = tk.Toplevel(
            self
        )

        window.title(
            "Ambito di conoscenza personalizzato"
        )

        window.resizable(
            False,
            False,
        )

        window.transient(
            self.winfo_toplevel()
        )

        tk.Label(
            window,
            text=(
                "Seleziona le librerie che Wiki22 "
                "può usare per questa domanda."
            ),
            anchor="w",
            justify="left",
            padx=18,
            pady=14,
        ).pack(
            fill="x"
        )

        variables = {}

        for row in rows:

            library_id = str(
                row["id"]
            )

            variable = tk.BooleanVar(
                value=(
                    library_id
                    in self.current_ids
                )
            )

            variables[
                library_id
            ] = variable

            tk.Checkbutton(
                window,
                text=str(
                    row.get(
                        "name",
                        library_id,
                    )
                ),
                variable=variable,
                anchor="w",
                padx=18,
            ).pack(
                fill="x",
                pady=3,
            )

        buttons = tk.Frame(
            window
        )

        buttons.pack(
            fill="x",
            padx=18,
            pady=14,
        )

        def apply():
            selected = [
                library_id
                for library_id, variable
                in variables.items()
                if variable.get()
            ]

            if not selected:

                messagebox.showwarning(
                    "Conoscenza personalizzata",
                    (
                        "Seleziona almeno una "
                        "libreria di conoscenza."
                    ),
                    parent=window,
                )

                return

            self.current_mode = (
                "CUSTOM"
            )

            self.current_ids = (
                selected
            )

            self._show_custom_label()

            window.destroy()

        tk.Button(
            buttons,
            text="Applica",
            command=apply,
            padx=14,
            pady=6,
        ).pack(
            side="right"
        )

        tk.Button(
            buttons,
            text="Annulla",
            command=window.destroy,
            padx=14,
            pady=6,
        ).pack(
            side="right",
            padx=(0, 8),
        )

    def _show_custom_label(
        self,
    ) -> None:

        rows = {
            str(row["id"]):
                str(
                    row.get(
                        "name",
                        row["id"],
                    )
                )
            for row in self._enabled()
        }

        names = [
            rows.get(
                library_id,
                library_id,
            )
            for library_id
            in self.current_ids
        ]

        display = ", ".join(
            names[:2]
        )

        if len(names) > 2:

            display += (
                f" +{len(names) - 2}"
            )

        label = (
            f"Personalizzata · {display}"
        )

        values = list(
            self.combo[
                "values"
            ]
        )

        values = [
            value
            for value in values
            if not str(
                value
            ).startswith(
                "Custom · "
            )
        ]

        values.insert(
            max(
                len(values) - 1,
                0,
            ),
            label,
        )

        self.combo[
            "values"
        ] = values

        self.option_map[
            label
        ] = (
            "CUSTOM",
            list(
                self.current_ids
            ),
        )

        self.choice.set(
            label
        )

    def environment(
        self,
    ) -> dict[str, str]:

        if (
            self.current_mode
            is None
        ):

            return {"WIKI22_SCOPE_MODE": "SINGLE", "WIKI22_SCOPE_LIBRARIES": ""}

        return {
            "WIKI22_SCOPE_MODE":
                self.current_mode,

            "WIKI22_SCOPE_LIBRARIES":
                ",".join(
                    self.current_ids
                ),
        }

    def describe(
        self,
    ) -> str:

        if self.current_mode is None:
            return "Nessuna libreria attiva"

        return (
            f"{self.current_mode}: "
            f"{', '.join(self.current_ids)}"
        )
