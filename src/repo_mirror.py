import pycurl
from io import BytesIO
import json
import subprocess
import argparse
import repo_dbmaint
from threading import Thread
from queue import Queue
from pathlib import Path
import random
import sys

curl = pycurl.Curl()
b = BytesIO()
curl.setopt(curl.WRITEDATA, b)
curl.setopt(curl.CONNECTTIMEOUT, 10)

# Construct an argument parser
all_args = argparse.ArgumentParser()

def main():   
    # Add arguments to the parser
    all_args.add_argument("-c", "--config", required=True,
                        help="Path to the config file which contains the appropriate settings")
    args = vars(all_args.parse_args())
    configFile = json.load(open(args["config"]))
    repoRoot = Path(configFile["maint_config"]["repo_root"])
    print("Version 1.0")
    if not repoRoot.exists():
        print(str(repoRoot.resolve()) +" doesn't exist. Check config.json.")
        exit
    
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
            countryCode = '?country='+response["countryCode"]
        else:
            countryCode = '?country='+str(configFile['mirror_config']["auto"]["generator"]["country_code"]).upper()
        protocols = configFile['mirror_config']["auto"]["generator"]["protocols"]
        ipVersions = configFile['mirror_config']["auto"]["generator"]["ip_versions"]
        enabledProtocols = "&protocol="+"&protocol=".join([i for i in protocols if protocols[i] == True])
        enabledIPVersions = "&ip_version="+"&ip_version=".join([i for i in ipVersions if ipVersions[i] == True])
        useMirrorStatus = ("&use_mirror_status=on" if configFile['mirror_config']["auto"]["generator"]["use_mirror_status"] == "on" else "")
        mirrorListURL = configFile['mirror_config']["auto"]["generator"]["url"]+countryCode+enabledProtocols+enabledIPVersions+useMirrorStatus
        curl.setopt(curl.URL, mirrorListURL)
        curl.perform()
        for line in [i for i in str(b.getvalue(), 'UTF-8').splitlines() if i.__contains__('#Server = ')]:
            mirrorList.append(line.split('#Server = ')[1])
    else:
        for server in configFile['mirror_config']["manual"]["servers"]:
            mirrorList.append(server["server"])

    ## Shuffle the list so we're not always hitting the same server
    random.shuffle(mirrorList)
    arch="x86_64"
    # Get all the repos and add them to the allRepos dict. with the value being the type of repo it is.
    allRepos=dict.fromkeys(configFile["maint_config"]["remote_repos"],"remote")

    try:
        allRepos.update(dict.fromkeys(configFile["maint_config"]["local_repos"],"local"))
    except:
        print("Local repo not specified")

    mirrorToUse = ""
    mirrorDepth = 0
    for fullUrl in mirrorList:
        # baseUrl = fullUrl.split('://')[1].split('/')[0]
        curlResults = True
        for repo,type in allRepos.items():
            if type == "remote":
                baseUrl = fullUrl.replace('$arch',arch).replace('$repo',repo)
                print('Trying '+baseUrl)
                curl.setopt(curl.FOLLOWLOCATION, True)
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
        
        if curlResults:
            print('Got reponse')

            mirrorToUse = fullUrl
            mirrorDepth = fullUrl.split('/$repo')[0].count('/')-2
            print("Mirror "+mirrorToUse)
            print("Depth "+str(mirrorDepth))
            break
        else:
            continue
    
    if mirrorToUse == "":
        print("Something went wrong, got no responses.")
        print("Exiting...")
        exit

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
           downloadUrl = mirrorToUse.replace('$arch',arch).replace('$repo',repo)
           databasePath = Path(repoRoot+'/'+'/'.join(downloadUrl.split('/')[-3:])+'/'+repo+'.db.tar.gz')
           runCommand = 'wget2 -e robots=off -N --no-if-modified-since -P "'+repoRoot+'" -nH -m --cut-dirs='+str(mirrorDepth)+' --no-parent --timeout=3 --accept="*.pkg.tar*" '+downloadUrl
           ignoreVerify = False

        parseDbThread = Thread(name="Thread-"+repo,target=lambda q, arg1,arg2: q.put(repo_dbmaint.parseDB(arg1,arg2)), args=(threadQueue, databasePath,ignoreVerify))
        commandList.append(runCommand)
        threadList.append(parseDbThread)

    for command in commandList:
        subprocess.run(command, shell=True)

    for thread in threadList:
        thread.start()
    
    print("Waiting to finish up..")
    for dbThread in threadList:
        dbThread.join()

    addedTotal = 0
    addedPackages = ""
    removedTotal = 0
    removedPackages = ""

    while not threadQueue.empty():
        result = threadQueue.get()
        addedTotal += result[0]
        addedPackages += result[1]
        removedTotal += result[2]
        removedPackages += result[3]

    if addedTotal > 0:
        print("New files added - run notify")
        scriptPath = Path(sys.argv[0]).parent.resolve()
        notifyCommand = 'python "'+str(scriptPath)+'/repo_notify.py" -c "'+args["config"]+'" -m "Added '+str(addedTotal)+' new packages.\n' + addedPackages + '"'
        print(notifyCommand)
        subprocess.run(notifyCommand, shell=True)
    
    print("Done")


if __name__ == "__main__":
    main()