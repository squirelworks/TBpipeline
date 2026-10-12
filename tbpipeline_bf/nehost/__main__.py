"""python3 -m tbpipeline_bf.nehost [--unpack] image [-o out]"""

import sys

from tbpipeline_bf.nehost.unfold import main as unfold_main
from tbpipeline_bf.nehost.unpack_optloader import main as unpack_main


def main():
    argv = sys.argv[1:]
    if "--unpack" in argv:
        argv.remove("--unpack")
        sys.argv = [sys.argv[0], *argv]
        return unpack_main()
    if not argv:
        print("usage: python3 -m tbpipeline_bf.nehost --unpack TB80RTM.EXE -o unpacked.exe", file=sys.stderr)
        print("       python3 -m tbpipeline_bf.nehost TB80RTM.EXE -o rtm_out", file=sys.stderr)
        return 2
    return unfold_main()


if __name__ == "__main__":
    sys.exit(main())
