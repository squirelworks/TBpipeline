# Known bugs

## Stage 2 does not open the book

The entry asks for `TB80.INI` and `TB80enu`, then DOS exit 0. Those paths are listed in `opens` because every open is logged. Only a `.tbk` or `.sbk` gets a handle. The fault string is why the reader still runs.

## render/ page count disagrees with the file count

Stage 2b says `render/ 18 pages`. Stage 2c says `render/ 23 pages`.

Both are right about a different thing. Eighteen is the number of pages that have something drawable. Twenty-three is the number of files, because a page can have more than one curve. P420 has four.

The two lines should say the same thing, or say which count they mean.
