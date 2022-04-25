import os
import subprocess
import glob
import argparse
import tarfile
import time
import numpy as np
from threading import Thread
from queue import Queue
from pathlib import Path

# Construct an argument parser
all_args = argparse.ArgumentParser()

def main():
    # Add arguments to the parser
    all_args.add_argument("-db", "--database", required=True,
                        help="Path to the database file /my/path/core.db.tar.gz")
    args = vars(all_args.parse_args())
    parseDB(Path(args['database']))

def verifyPKGFiles(fileArray,databaseName,ignoreVerify):
    availableFiles = {}
    delFiles = {}

    for pkgFilePath in fileArray:
        readPkgCommand='tar -xOf "'+pkgFilePath+'" .PKGINFO --no-recursion'
        ## Add universal_newlines=True below to remove BYTES indicator if needed
        pkgInfoContents = subprocess.run(readPkgCommand, shell=True, stdout=subprocess.PIPE).stdout.splitlines()
        pkgFileName = str(Path(pkgFilePath).name)
        try:
            newPackage = Package(pkgInfoContents, databaseName, pkgFileName, Path(pkgFilePath), ignoreVerify=ignoreVerify)
            if newPackage.name not in availableFiles.keys():
                availableFiles[newPackage.name] = newPackage
            else:
                if availableFiles[newPackage.name].builddate < newPackage.builddate:
                    delFiles[availableFiles[newPackage.name].filename] = availableFiles[newPackage.name].filename
                    availableFiles[newPackage.name] = newPackage
        except:
            if(Path.exists(Path(pkgFilePath))):
                print("Invalid package.. delete it")
                os.remove(pkgFilePath)

    return (availableFiles,delFiles)

def parsePKGFiles(filePaths,databaseName,ignoreVerify):
    threadList = []
    threadQueue = Queue()
    filePathArray = np.array(filePaths)
    chunk_size = len(filePaths) / 5 
    filePathSplit = np.array_split(filePathArray, len(filePaths) // chunk_size)
    availableFiles = {}
    delFiles = {}


    x = 0
    for fileArray in filePathSplit:
        x += 1
        VerifyPKGThread = Thread(name=databaseName+"-verify-"+str(x),target=lambda q, arg1,arg2,arg3: q.put(verifyPKGFiles(arg1,arg2,arg3)), args=(threadQueue,fileArray, databaseName,ignoreVerify))
        threadList.append(VerifyPKGThread)
    
    for thread in threadList:
        thread.start()

    print("Waiting to finish up..")
    for dbThread in threadList:
        dbThread.join()

    while not threadQueue.empty():
        result = threadQueue.get()
        availableFiles = availableFiles | result[0]
        delFiles = delFiles | result[1]
    
    return (availableFiles,delFiles)

def parseDB(databasePath: Path, ignoreVerify: bool = False):
    rootFolder = Path(databasePath.parent)
    databaseName = databasePath.name

    returnObject = {}

    availableFiles = {}
    keepFiles = {}
    delFiles = {}

    filePaths=sorted(glob.glob(str(rootFolder)+"/*.pkg.tar.*[!.sig]"))

    ## Quick verify of database
    databaseReady = False
    print("Checking that the database is valid and not corrupt.")
    databaseCheckCommand = 'repo-add "'+str(databasePath)+'"'
    checkError = subprocess.run(databaseCheckCommand, shell=True, universal_newlines=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE).stderr.splitlines()

    if len(checkError) <= 0:
        print(databaseName+" database is GOOD!")
        databaseReady = True
    else:
        print(databaseName+" database is BAD :(, rebuild required.")

        deleteFiles = glob.glob(str(rootFolder)+"/"+databaseName.split(".db.")[0]+"*")
        for file in deleteFiles:
            if os.path.exists(file) :
                os.remove(file)

    # get the start time
    st = time.time()
    pkgFiles = parsePKGFiles(filePaths,databaseName,ignoreVerify)
    # get the end time
    et = time.time()

    # get the execution time
    elapsed_time = et - st
    print('Execution time:', elapsed_time, 'seconds')

    availableFiles = pkgFiles[0]
    delFiles = pkgFiles[1]

    print(databaseName+": Repo directory contains " + str(len(availableFiles)) + " unique packages.")

    databaseFiles = []
   
    if databaseReady:
        if Path.exists(databasePath):
            print(databaseName+": Database exists, indexing..")
            dbFile = tarfile.open(databasePath)
            for tarinfo in dbFile:
                if tarinfo.isfile() and tarinfo.name.split('/')[1] == "desc":
                    descFileContents = dbFile.extractfile(tarinfo).readlines()
                    # don't verify because all files that exist in the directory have already been verified
                    tarPackage = Package(pkginfo=descFileContents, database=databaseName, filename="", fullPath=Path(databasePath), ignoreVerify=True)
                    ## Debug
                    # if "xmobar" in tarPackage.name:
                    databaseFiles.append(tarPackage)
        else:
            print(databaseName+": Database doesn't exist.")

        for file in databaseFiles:
            if not Path.exists(Path(file.fullPath)):
                delFiles[file.filename] = file.filename


    for file in availableFiles.values():
        inDatabase = False
        if not file.verified:
            delFiles[file.filename] = file.filename
            continue
        else :
            for dbFile in databaseFiles:
                if dbFile.name == file.name:
                    if file.builddate < dbFile.builddate:
                        delFiles[file.filename] = file.filename
                        print(databaseName+": Old package, remove "+file.filename+" from the database.")
                    elif file.builddate > dbFile.builddate:
                        delFiles[dbFile.filename] = dbFile.filename
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

    # Clean up the database
    for file in delFiles.keys():
        tempCommand = databaseRemCommand + ' "'+str(file)+'"'

        # Consolidate the repo-remove command to save time
        if len(tempCommand) > maxCommandLength:
            subprocess.run(databaseRemCommand, shell=True)
            # Restart the databaseRemCommand
            databaseRemCommand = 'repo-remove "'+str(databasePath)+ '" "'+str(file)+'"'
            wasRun = True
        else:
            databaseRemCommand = tempCommand
            wasRun = False
    
    # Run the repo-remove command if it hasn't been run yet
    if len(delFiles) > 0 and not wasRun and Path.exists(databasePath):
        repoRemoveSuccess = subprocess.run(databaseRemCommand, shell=True, universal_newlines=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE).stderr.splitlines()
        if len(repoRemoveSuccess) <= 0:
            print("Modified Database success")
        else:
            print("Modified Database failed. Rebuild required.")
            deleteFiles = glob.glob(str(rootFolder)+"/"+databaseName.split(".db.")[0]+"*")
            returnObject["Redownload"] = True
            for file in deleteFiles:
                if os.path.exists(file) :
                    os.remove(file)
            return returnObject

    # Delete the actual files from the system now, if they're still there
    for file in delFiles.keys():
        fileName = delFiles[file]
        filePath = Path(str(rootFolder)+"/"+fileName).resolve()
        filePathSig = Path(str(filePath)+".sig").resolve()

        if(Path.exists(filePath)):
            print("delete "+fileName)
            os.remove(filePath)

        if(Path.exists(filePathSig)):
            os.remove(filePathSig)
    
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
        modifyDatabase = subprocess.run(databaseAddCommand, shell=True, universal_newlines=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE).stderr.splitlines()
        if len(modifyDatabase) <= 0:
            print("Modified Database success")
        else:
            print("Modified Database failed")

    reDownload = False

    for file in availableFiles:
        if not availableFiles[file].verified:
            reDownload = True

    keepFilesString = "\n".join(str(x) for x in keepFiles.keys())
    delFilesString = "\n".join(str(x) for x in delFiles.keys())
    
    returnObject["Repo"] = databaseName.split('.')[0]
    returnObject["Added Count"] = len(keepFiles)
    returnObject["Added String"] = returnObject["Repo"] + " added " + str(returnObject["Added Count"]) + " files\n"
    returnObject["Deleted Count"] = len(delFiles)
    returnObject["Deleted String"] = returnObject["Repo"] + " deleted " + str(returnObject["Deleted Count"]) + " files\n"
    returnObject["Redownload"] = reDownload
    

    #returnArray = [len(keepFiles),keepFilesString , len(delFiles), delFilesString, reDownload, "needs redownload"]
    
    return returnObject


class Package:
    # init values
    # filename, name, version, builddate, fullPath, verified

    def __init__(self, pkginfo: list[bytes], database, filename, fullPath, ignoreVerify):
        self.fullPath = str(fullPath)
        if ignoreVerify:
            self.verified = True
        else :
            self.verified = False
            self.verify()

        self.parsePkgInfo(pkginfo, database, filename)

    def verify(self):
        verifyCommand='pacman-key --verify "'+self.fullPath+'.sig" "'+self.fullPath+'"'
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

        if(name in filename):
            self.filename = filename
            self.name = name
            self.version = version
            self.builddate = int(builddate)
            self.fullPath = self.fullPath.replace(database,filename)
            print(database+": Read Package - " + self.name)
        else:
            print("Incorrect package for sig")
            


if __name__ == "__main__":
    main()
