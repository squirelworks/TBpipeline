# nehost history

Early experimental passes of the Win16 OPTLOADER host (pass 01 through pass 12, including the original `unfold.py` scaffold and `cmpcall.c`) lived under `nehost/` in the `squirelworks.github.io` archive.

Those versions have been superseded by the current implementation in this directory (`unfold.py`, `pass04.py`, `scaffold.py`, etc.). The early passes demonstrated the basic BootApp / LoadAppSeg contract and the first Unicorn-based 16-bit host; the current code adds proper relocation binding, stack handling, resource indexing, and the full KERNEL/USER surface needed for further progress.

The original early files are no longer required on the website and have been removed from `squirelworks.github.io` as part of pruning. The dedicated history of the reverse-engineering work is in the `tbworldview` repository.

This note is kept so the historical context remains available if someone runs into issues with the older scaffold or wants to understand the evolution of the host.
