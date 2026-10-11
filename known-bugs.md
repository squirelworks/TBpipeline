# Known bugs

## render/ page count disagrees with the file count

Stage 2b says `render/ 18 pages`. Stage 2c says `render/ 23 pages`.

Both are right about a different thing. Eighteen is the number of pages that have something drawable. Twenty-three is the number of files, because a page can have more than one curve. P420 has four.

The two lines should say the same thing, or say which count they mean.
