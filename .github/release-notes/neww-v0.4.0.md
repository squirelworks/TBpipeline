# TBpipeline neww 0.4.0

neww shows ToolBook's modal dialog boxes. On Logic Families, Lesson Exit now asks before it closes, as it does in ToolBook. `bf` is unchanged and stays `1.0.0r6`.

## New since neww-v0.3.0

- **Modal dialog boxes (roadmap #201 T9b, #217).** `USER.240 DialogBoxIndirectParam` builds the box from its template, with Wine's dialog units, font and placement, and runs the modal loop through the program's own message gates. It returns `EndDialog`'s value. `#32770` and `DefDlgProc` handle Tab, Escape and Return, the default button, and `WM_CLOSE`. `GetDlgItem`, `SetDlgItemText`, `GetDlgItemText` and `SendDlgItemMessage` work. On P900, Lesson Exit shows "Are you sure you want to Exit the Lesson?" with Yes and No. No leaves the menu as it was, and Yes lets ToolBook close the book. Every ToolBook `request` box goes through the same call. Sources: Wine `2528aff2` `dlls/user.exe16/dialog.c`, `dlls/user32/dialog.c`, `dlls/user32/defdlg.c`.

## Correction: already in neww-v0.3.0

The neww-v0.3.0 notes listed T9a as in review, but it had merged before that tag was cut:

- **`Button` and `Static` controls (T9a, #215).** Push buttons and default push buttons paint as Wine's `PB_Paint` does. A click sends `BN_CLICKED` to the parent. Text statics draw word-wrapped in the parent's colour. Any other button or static style stops by name rather than being made up.

## Still open

- T5: one bitmap through `TB80BMP`.
- T6: widget placement.

## Next release point

`neww-v0.5.0` when T5 is merged, so a compressed book picture comes back as a DIB.
