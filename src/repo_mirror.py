import pycurl
from io import BytesIO
import json
import subprocess
import argparse
from threading import Thread
from queue import Queue
from pathlib import Path
import random
import sys
import re
import repo_dbmaint
from html.parser import HTMLParser

curl = pycurl.Curl()
b = BytesIO()
curl.setopt(curl.WRITEDATA, b)
curl.setopt(curl.CONNECTTIMEOUT, 10)
curl.setopt(curl.FOLLOWLOCATION, 1)

# Construct an argument parser
all_args = argparse.ArgumentParser()
ARCH="x86_64"

print("Version 1.2")

# Used to remove/reset the data in the BytesIO() object
# Otherwise the data is appended to it and you'll need
# to account for the offset between the new data and the old
def resetBytes():
    b.truncate(0)
    b.seek(0)

# Reads the config, and parses all returned URLs if it's active
# and matches the specified countrycode.
def getMirrors(configFile,countryCode):
    mirrorUrls = []
    generatorConfig = configFile['mirror_config']["auto"]["generator"]

    enabledProtocols = [i for i in generatorConfig["protocols"] if generatorConfig["protocols"][i] == True]
    mirrorListURL = generatorConfig["url"]

    curl.setopt(curl.URL, mirrorListURL)
    curl.perform()
    mirrorDetails = json.loads(str(b.getvalue(), 'UTF-8'))
    resetBytes()
    for url in [i for i in mirrorDetails['urls'] if i["country_code"] == countryCode and i["active"] == True]:
        if url["protocol"] in enabledProtocols and url["last_sync"]:
            mirrorUrls.append(url)

    # sort by last sync
    mirrorUrls.sort(reverse=True,key=lambda i: i["last_sync"])

    return mirrorUrls

# For each mirror URL returned, we attempt to connect
# if connection is successful we return that working URL
def getWorkingMirror(configFile,allRepos):
    mirrorList = []

    if configFile['mirror_config']["method"] == "auto":
        if configFile['mirror_config']["auto"]["generator"]["country_code"] == "geoip":
            curl.setopt(curl.URL, 'icanhazip.com')
            curl.perform()
            ipAddress = str(b.getvalue(), 'UTF-8').splitlines()[0]
            curl.setopt(curl.URL, 'http://ip-api.com/json/'+ipAddress)
            curl.perform()
            response = json.loads(str(b.getvalue(), 'UTF-8').splitlines()[1])
            print("Country Code: "+response["countryCode"])
            countryCode = response["countryCode"]
        else:
            countryCode = str(configFile['mirror_config']["auto"]["generator"]["country_code"]).upper()
        mirrorList = getMirrors(configFile,countryCode)
    else:
        for server in configFile['mirror_config']["manual"]["servers"]:
            # Extracting the protocol from the server URL
            protocol = server["server"].split("://")[0]

            # Creating a dictionary for the server with protocol and URL fields
            server_info = {
                "protocol": protocol,
                "url": server["server"],
                "emptyUrl": server["server"].split("$repo")[0]
            }

            # Appending the server info dictionary to the mirrorList
            mirrorList.append(server_info)

    ## Shuffle the list so we're not always hitting the same server
    ##random.shuffle(mirrorList)

    mirrorToUse = ""
    mirrorDepth = 0
    for mirror in mirrorList:
        curlResults = True
        for repo,type in allRepos.items():
            # Remote = non-locally hosted (i.e not built AUR packages)
            if type == "remote":
                if "http" in mirror["protocol"] or "https" in mirror["protocol"]:
                    baseUrl = mirror["url"].replace('$arch',ARCH).replace('$repo',repo)
                    print('Trying '+baseUrl)
                    curl.setopt(curl.URL, baseUrl)
                    try:
                        curl.perform()
                    except:
                        print('Problem retrieving URL, skipping..')
                        break

                    curlResponse = curl.getinfo(pycurl.RESPONSE_CODE)
                    print('Response: '+str(curlResponse)+' for '+repo)
                    if curlResponse != 200:
                        curlResults = False
                        break
                else:
                    rsyncCommand = 'rsync -qlptH --safe-links --delete-delay --delay-updates "--timeout=600" "--contimeout=60" --no-motd '+ mirror["emptyUrl"]
                    proc = subprocess.run(rsyncCommand, shell=True)
                    if proc.returncode != 0:
                        curlResults = False
                        break

        if curlResults:
            print('Got reponse')
            if mirror["url"].find("$repo") == -1:
                print("Append repo/arch string")
                mirrorToUse = mirror["url"]+'$repo/os/$arch'
            else:
                mirrorToUse = mirror["url"]

            mirrorDepth = mirror["url"].split("$repo")[0].count('/')-2
            print("Mirror "+mirrorToUse)
            print("Depth "+str(mirrorDepth))
            return {"url":mirrorToUse,"depth":mirrorDepth,"protocol":mirror["protocol"]}
        else:
            continue

    if mirrorToUse == "":
        print("Something went wrong, got no responses.")
        print("Exiting...")
        exit

def runDownloadThreads(repoRoot,mirrorToUse,allRepos):
    threadQueue = Queue()
    threadList = []
    repoRoot = str(repoRoot.resolve())
    commandList = []

    for repo,type in allRepos.items():
        ignoreVerify = False

        if type == "local":
            runCommand = 'yay -Syy;aur sync -d "'+ repo +'" -u --noview --noconfirm'
            databasePath = Path(repoRoot+'/'+repo+'/'+repo+'.db.tar.gz')
            ignoreVerify = True
        else:
            downloadUrl = mirrorToUse["url"].replace('$arch',ARCH).replace('$repo',repo)
            databasePath = Path(repoRoot+'/'+'/'.join(downloadUrl.split('/')[-3:])+'/'+repo+'.db.tar.gz')
            databasePath.parent.mkdir(parents=True, exist_ok=True)
            if "http" in mirrorToUse["protocol"] or "https" in mirrorToUse["protocol"]:
                runCommand = 'wget2 -e robots=off -N --no-if-modified-since -P "'+repoRoot+'" -nH -m --cut-dirs='+str(mirrorToUse["depth"])+' --no-parent --timeout=3 --accept="*.pkg.tar*" '+downloadUrl
            else:
                # rsync
                runCommand = 'rsync -vrLptH --include="*.pkg.tar.zst*" --include="*.pkg.tar.xz*" --exclude="*" --delete-delay --inplace "--timeout=600" "--contimeout=60" --no-motd '+downloadUrl+'/ '+str(databasePath.parent)+"/"

        parseDbThread = Thread(name="Thread-"+repo,target=lambda q, arg1,arg2,arg3: q.put(repo_dbmaint.parseDB(arg1,arg2,arg3)), args=(threadQueue, databasePath,"",ignoreVerify))
        commandList.append(runCommand)
        threadList.append(parseDbThread)


    for command in commandList:
        subprocess.run(command, shell=True)

    for thread in threadList:
        thread.start()

    print("Waiting to finish up..")
    for dbThread in threadList:
        dbThread.join()

    return threadQueue


def main():
    # Add arguments to the parser
    all_args.add_argument("-c", "--config", required=True,
                        help="Path to the config file which contains the appropriate settings")
    args = vars(all_args.parse_args())

    configFile = json.load(open(args["config"]))

    repoRoot = Path(configFile["maint_config"]["repo_root"])
    doNotify = False

    if configFile:
        services = configFile["service_config"]["notifiers"]
        for service in services:
            if service["notifier"]["enabled"]:
                doNotify = True

    if not repoRoot.exists():
        print(str(repoRoot.resolve()) +" doesn't exist. Check config.json.")
        exit

    # Get all the repos and add them to the allRepos dict. with the value being the type of repo it is.
    allRepos=dict.fromkeys(configFile["maint_config"]["remote_repos"],"remote")

    try:
        allRepos.update(dict.fromkeys(configFile["maint_config"]["local_repos"],"local"))
    except:
        print("Local repo not specified")

    MAX_RETRY = 3
    readyToContinue = False
    attempts = 0
    reposToDownload = allRepos
    addedTotal = 0
    addedPackages = ""
    removedTotal = 0
    removedPackages = ""

    mirrorToUse = getWorkingMirror(configFile=configFile, allRepos=reposToDownload)

    while (not readyToContinue and attempts < MAX_RETRY):
        attempts += 1

        readyToContinue = True
        threadQueue = runDownloadThreads(repoRoot=repoRoot,mirrorToUse=mirrorToUse,allRepos=reposToDownload)

        while not threadQueue.empty():
            returnObject = threadQueue.get()

            if(not returnObject):
                continue

            # Needs redownload
            if(returnObject["Redownload"]):
                readyToContinue = False
                continue

            #Remove repo from download list
            reposToDownload.pop(returnObject["Repo"])
            if returnObject["Added Count"] > 0 or returnObject["Deleted Count"] > 0:
                addedTotal += returnObject["Added Count"]
                addedPackages += returnObject["Added String"]
                removedTotal += returnObject["Deleted Count"]
                removedPackages += returnObject["Deleted String"]

    if(doNotify):
        print("Run notify")
        scriptPath = Path(sys.argv[0]).parent.resolve()
        notifyCommand = 'python "'+str(scriptPath)+'/repo_notify.py" -c "'+args["config"]+'" -m "'+ addedPackages + ' ' + removedPackages +'"'
        print(notifyCommand)
        subprocess.run(notifyCommand, shell=True)

    print("Done")


if __name__ == "__main__":
    main()