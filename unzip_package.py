import tarfile
import argparse
import re
from pathlib import Path
import shutil
import os
import glob






# Open the .tgz file
# with tarfile.open("archive.tgz", "r:gz") as tar:
#     # Extract all contents to the current directory
#     tar.extractall(path=".")



def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=package_file, required=True, help="Input package tgz file")
    parser.add_argument("--output", required=True, help="Output folder")

    args = parser.parse_args()


    if os.path.exists(args.output):
        shutil.rmtree(args.output)
        print(f"Previously existing folder '{args.output}' and its contents have been deleted.")
    else:
        print(f"The folder '{args.output}' does not exist.")
    
    Path(args.output).mkdir(parents=True, exist_ok=True)

    # Open the .tgz file
    #with tarfile.open(args.input, "r:gz") as tar:
    #    tar.extractall(path=args.output)

    filename = args.input
    if os.path.exists(filename) and os.path.getsize(filename) > 0:                
        try:                
            with tarfile.open(filename, "r:gz") as tar:                
                tar.extractall(path=args.output)
                print("Extraction complete.")                
        except tarfile.ReadError:                
            print("File is not a valid tar archive or is corrupted.")                
    else:                
        print("File does not exist or is empty.")


def package_file(string):
    """Argparse `type=` helper: ensure the input package file exists.
    """
    if glob.glob(string):
        print(f"{string} found.")
        return string
    else:
        print("The package tgz file needs to exist.")
        return None



if __name__ == "__main__":
    main()