# Known bugs

## Stage 2 does not open the book

The entry asks for `TB80.INI` and `TB80enu`, then DOS exit 0. Those paths are listed in `opens` because every open is logged. Only a `.tbk` or `.sbk` gets a handle. Nothing is rendered unless you pass `--dbgrender`.
