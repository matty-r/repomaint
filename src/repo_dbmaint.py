import os
import subprocess
import glob
import argparse
import tarfile
from pathlib import Path

# Construct an argument parser
all_args = argparse.ArgumentParser()

def main():
    # Add arguments to the parser
    all_args.add_argument("-db", "--database", required=True,
                        help="Path to the database file /my/path/core.db.tar.gz")
    args = vars(all_args.parse_args())
    parseDB(Path(args['database']))

def parseDB(databasePath: Path, ignoreVerify: bool = False) -> str:
    rootFolder = Path(databasePath.parent)
    databaseName = databasePath.name

    availableFiles = []
    

    for pkgFilePath in glob.glob(str(rootFolder)+"/*.pkg.tar.*[!.sig]"):
        readPkgCommand='tar xvf "'+pkgFilePath+'" .PKGINFO --to-command=cat'
        ## Add universal_newlines=True below to remove BYTES indicator if needed
        pkgInfoContents = subprocess.run(readPkgCommand, shell=True, stdout=subprocess.PIPE).stdout.splitlines()
        pkgFileName = str(Path(pkgFilePath).name)
        try:
            newPackage = Package(pkgInfoContents, databaseName, pkgFileName, Path(pkgFilePath))
            if ignoreVerify:
                newPackage.verified = True

            availableFiles.append(newPackage)
        except:
            if(Path.exists(Path(pkgFilePath))):
                print("Invalid package.. delete it")
                os.remove(pkgFilePath)

    print(databaseName+": Repo directory contains " + str(len(availableFiles)) + " files.")

    databaseFiles = []
    keepFiles = {}
    delFiles = {}

    if Path.exists(databasePath):
        print(databaseName+": Database exists, indexing..")
        dbFile = tarfile.open(databasePath)
        for tarinfo in dbFile:
            if tarinfo.isfile() and tarinfo.name.split('/')[1] == "desc":
                descFileContents = dbFile.extractfile(tarinfo).readlines()
                tarPackage = Package(pkginfo=descFileContents, database=databaseName, filename="", fullPath=Path(databasePath))
                if ignoreVerify:
                    tarPackage.verified = True
                    
                databaseFiles.append(tarPackage)
    else:
        print(databaseName+": Database doesn't exist.")

    for file in databaseFiles:
        if not Path.exists(Path(file.fullPath)):
            delFiles[file.name] = file.filename

    for file in availableFiles:
        inDatabase = False
        if not file.verified:
            delFiles[file.name] = file.filename
        else :
            for dbFile in databaseFiles:
                if dbFile.name == file.name:
                    if file.builddate < dbFile.builddate:
                        delFiles[file.name] = file.filename
                        print(databaseName+": Old package, remove "+file.filename+" from the database.")
                    elif file.builddate > dbFile.builddate:
                        delFiles[dbFile.name] = dbFile.filename
                        print(databaseName+": Old package, remove " + dbFile.filename+" from the database.")
                        keepFiles[file.name] = file.filename
                        print(databaseName+": Updated package, add " + file.filename+" into the database.")

                    inDatabase = True
                    break

        if not inDatabase:
            keepFiles[file.name] = file.filename
            print(databaseName+": Will add " + file.filename+" into the database.")
            
    print(databaseName+": Adding " + str(len(keepFiles)) + " files.")
    print(databaseName+": Deleting " + str(len(delFiles)) + " files.")
    
    databaseRemCommand = 'repo-remove "'+str(databasePath)+'"'
    maxCommandLength = int(int(subprocess.run('getconf ARG_MAX', shell=True, stdout=subprocess.PIPE,universal_newlines=True).stdout.splitlines()[0])/16)
    wasRun = False

    for file in delFiles.keys():
        fileName = delFiles[file]
        filePath = Path(str(rootFolder)+"/"+fileName).resolve()
        filePathSig = Path(str(filePath)+".sig").resolve()
        tempCommand = databaseRemCommand + ' "'+str(file)+'"'

        if(Path.exists(filePath)):
            print("delete "+fileName)
            os.remove(filePath)

        if(Path.exists(filePathSig)):
            os.remove(filePathSig)

        if len(tempCommand) > maxCommandLength:
            subprocess.run(databaseRemCommand, shell=True)
            # Restart the databseCommand
            databaseRemCommand = 'repo-remove "'+str(databasePath)+ '" "'+str(file)+'"'
            wasRun = True
        else:
            databaseRemCommand = tempCommand
            wasRun = False
    
    if len(delFiles) > 0 and not wasRun:
        subprocess.run(databaseRemCommand, shell=True)
    
    databaseAddCommand = 'repo-add "'+str(databasePath)+'"'
    
    wasRun = False

    for file in keepFiles.keys():
        fileName = keepFiles[file]
        filePath = Path(str(rootFolder)+"/"+fileName).resolve()
        tempCommand = databaseAddCommand + ' "'+str(filePath)+'"'

        # here we're batching the command so it's more efficient
        if len(tempCommand) > maxCommandLength:
            subprocess.run(databaseAddCommand, shell=True)
            # Restart the databseCommand
            databaseAddCommand = 'repo-add "'+str(databasePath)+ '" "'+str(filePath)+'"'
            wasRun = True
        else :
            databaseAddCommand = tempCommand
            wasRun = False

    if len(keepFiles) > 0 and not wasRun:
        subprocess.run(databaseAddCommand, shell=True)
    
    return len(keepFiles)


class Package:
    # init values
    # filename, name, version, builddate, fullPath, verified

    def __init__(self, pkginfo: list[bytes], database, filename, fullPath):
        self.fullPath = str(fullPath)
        self.verified = False
        self.parsePkgInfo(pkginfo, database, filename)

    def verify(self):
        verifyCommand='pacman-key --verify "'+self.fullPath+'.sig" "'+self.fullPath+'"'
        ## verifyCommand='pacman-key --verify "/mnt/repodata/repos/extra/os/x86_64/garcon-4.16.1-1-x86_64.pkg.tar.zst.sig" "/mnt/repodata/repos/extra/os/x86_64/zsh-5.8-1-x86_64.pkg.tar.zst"'
        ## this throws an error if it can't verify it with the signature.
        ## also hide the output from the verify command.
        try:
            subprocess.run(verifyCommand, shell=True, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT).check_returncode()
            self.verified = True
        except:
            print("Failed signature verification.")
            self.verified = False

    def parsePkgInfo(self, pkginfo: list[bytes], database, filename):
        try:
            filename = str(pkginfo[pkginfo.index(b'%FILENAME%\n') + 1],
                       'UTF-8').split("\n")[0]
            name = str(pkginfo[pkginfo.index(b'%NAME%\n') + 1],
                       'UTF-8').split("\n")[0]
            version = str(pkginfo[pkginfo.index(
                b'%VERSION%\n') + 1], 'UTF-8').split("\n")[0]
            builddate = str(pkginfo[pkginfo.index(
                b'%BUILDDATE%\n') + 1], 'UTF-8').split("\n")[0]
            arch = str(pkginfo[pkginfo.index(b'%ARCH%\n') + 1],
                       'UTF-8').split("\n")[0]
        except:
            valueList = {"name": "pkgname = ", "version": "pkgver = ",
                         "builddate": "builddate = ", "arch": "arch = "}
            for valueKey in valueList.keys():
                for line in pkginfo:
                    readLine = str(line, 'UTF-8')
                    if valueList[valueKey] in readLine:
                        valueList[valueKey] = readLine.replace(
                            valueList[valueKey], "").replace("\n", "")
                        break

            name = valueList["name"]
            version = valueList["version"]
            builddate = valueList["builddate"]
            arch = valueList["arch"]

        self.filename = filename
        self.name = name
        self.version = version
        self.builddate = int(builddate)
        self.fullPath = self.fullPath.replace(database,filename)
        print(database+": Read Package - " + self.name)
        self.verify()
            


if __name__ == "__main__":
    main()
