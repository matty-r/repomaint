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

# Construct an argument parser
all_args = argparse.ArgumentParser()

def main():   
    # Add arguments to the parser
    all_args.add_argument("-c", "--config", required=True,
                        help="Path to the config file which contains the appropriate settings")
    args = vars(all_args.parse_args())
    configFile = json.load(open(args["config"]))
    repoRoot = Path(configFile["maint_config"]["repo_root"])

    if not repoRoot.exists():
        print(str(repoRoot.resolve()) +" doesn't exist. Check config.json.")
        exit

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
        mirrorList = []
        for line in [i for i in str(b.getvalue(), 'UTF-8').splitlines() if i.__contains__('#Server = ')]:
            mirrorList.append(line.split('#Server = ')[1])
    else:
        mirrorList = configFile['mirror_config']["method"]["manual"]["servers"]["server"]

    ## Shuffle the list so we're not always hitting the same server
    random.shuffle(mirrorList)
    
    mirrorToUse = ""
    mirrorDepth = 0
    for fullUrl in mirrorList:
        baseUrl = fullUrl.split('://')[1].split('/')[0]
        print('Trying '+baseUrl)
        curl.setopt(curl.URL, baseUrl)
        curl.perform()
        if curl.getinfo(pycurl.RESPONSE_CODE) == 200:
            print('Got reponse')
            mirrorToUse = fullUrl
            mirrorDepth = fullUrl.split('/$repo')[0].count('/')-2
            print("Mirror "+mirrorToUse)
            print("Depth "+str(mirrorDepth))
            break
    
    if mirrorToUse == "":
        print("Something went wrong, got no reponses.")
        print("Exiting...")
        exit

    webMirrorRepos=configFile["maint_config"]["remote_repos"]
    arch="x86_64"

    threadQueue = Queue()
    threadList = []
    repoRoot = str(repoRoot.resolve())
    for repo in webMirrorRepos:
        downloadUrl = mirrorToUse.replace('$arch',arch).replace('$repo',repo)
        databasePath = Path(repoRoot+'/'+'/'.join(downloadUrl.split('/')[-3:])+'/'+repo+'.db.tar.gz')
        parseDbThread = Thread(name="Thread-"+repo,target=lambda q, arg1: q.put(repo_dbmaint.parseDB(arg1)), args=(threadQueue, databasePath))
        downloadCommand = 'wget2 -e robots=off -P "'+repoRoot+'" -nH -m --cut-dirs='+str(mirrorDepth)+' --no-parent --timeout=3 --accept="*.pkg.tar*" '+downloadUrl
        subprocess.run(downloadCommand, shell=True)
        ## add the db creation/parsing to a thread to do it in the background while the rest of the repos are mirrored
        print("Launch thread..")
        parseDbThread.start()
        threadList.append(parseDbThread)
    
    print("Waiting to finish up..")
    for dbThread in threadList:
        dbThread.join()

    addedTotal = 0

    while not threadQueue.empty():
        result = threadQueue.get()
        addedTotal += result

    
    if addedTotal > 0:
        print("New files added - run notify")
        scriptPath = Path(sys.argv[0]).parent.resolve()
        notifyCommand = 'python "'+str(scriptPath)+'/repo_notify.py" -c "'+args["config"]+'" -m "Added '+str(addedTotal)+' new packages."'
        print(notifyCommand)
        subprocess.run(notifyCommand, shell=True)
    
    print("Done")


if __name__ == "__main__":
    main()