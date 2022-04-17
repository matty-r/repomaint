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

print("Version 1.1")

def resetBytes():
    b.truncate(0)
    b.seek(0)

class MyHTMLParser(HTMLParser):
    tagData = ""

    def handle_data(self, data):
        self.tagData = data.strip()

class HtmlTable():
    tableHtml = ""
    tableHeaders = []
    tableData = []
    parser = MyHTMLParser()

    def __init__(self,html,idOrClass) -> None:
        self.tableHtml = html
        tableRegex = '<table(.*?)/table>'

        tableHtml = re.finditer(tableRegex,html)
        for table in tableHtml:
            if idOrClass in table.group(1):
                self.tableHtml = table.group(1)
                break

        self.setTableHeaders()
        self.setTableData()


    def setTableHeaders(self):
        tableHeaders = []
        thRegex = '<th>(.*?)</th>'

        for match in re.finditer(thRegex,self.tableHtml):
            tableHeaders.append(match.group(1))

        self.tableHeaders = tableHeaders

    def setTableData(self):
        trRegex = '<tr>(.*?)</tr>'
        tdRegex = '<td(.*?)/td>'

        for match in re.finditer(trRegex,self.tableHtml):
            if '"country"' in match.group(0) and 'rsync' in match.group(0):
                rsyncSite = {}
                for match in re.finditer(tdRegex,match.group(0)):
                    self.parser.feed(match.group(0))
                    rsyncSite[self.tableHeaders[len(rsyncSite)]] = self.parser.tagData

                self.tableData.append(rsyncSite)

def getRsyncUrls(configFile):
    rsyncMirrors = []
    
    rsyncMirrorUrl = configFile['mirror_config']["auto"]["generator"]["rsync_url"]

    curl.setopt(curl.URL, rsyncMirrorUrl)
    curl.perform()
    rsyncHtml = str(b.getvalue(), 'UTF-8').replace("\n", "")
    resetBytes()

    # curl.setopt(curl.URL,"https://raw.githubusercontent.com/annexare/Countries/master/data/countries.json")
    # curl.perform()
    # countries = json.loads(str(b.getvalue(), 'UTF-8'))
    # resetBytes()

    rsyncMirrors = HtmlTable(rsyncHtml,'class="results"')
    rsyncDetailsArray = []

    for mirror in rsyncMirrors.tableData:
        curl.setopt(curl.URL, rsyncMirrorUrl+mirror["Server"]+"/json")
        curl.perform()
        mirrorDetails = json.loads(str(b.getvalue(), 'UTF-8'))
        resetBytes()
        
        for url in mirrorDetails["urls"]:
            mirror[url["protocol"]] = url["url"]
            mirror[url["country_code"]] = url["country_code"]

    # australianRepos = []
    # for rsyncRepo in [i for i in rsyncMirrors.tableData if 'Australia' in i["Country"]]:
    #     australianRepos.append(rsyncRepo)

    print("table stuff")


def getMirrors(configFile,countryCode):
    mirrorUrls = []
    generatorConfig = configFile['mirror_config']["auto"]["generator"]

    enabledProtocols = [i for i in generatorConfig["protocols"] if generatorConfig["protocols"][i] == True]
    mirrorListURL = generatorConfig["mirror_json"]

    curl.setopt(curl.URL, mirrorListURL)
    curl.perform()
    mirrorDetails = json.loads(str(b.getvalue(), 'UTF-8'))
    resetBytes()
    for url in [i for i in mirrorDetails['urls'] if i["country_code"] == countryCode and i["active"] == True]:
        if url["protocol"] in enabledProtocols:
            mirrorUrls.append(url)

    return mirrorUrls

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
            mirrorList.append(server["server"])

    ## Shuffle the list so we're not always hitting the same server
    random.shuffle(mirrorList)

    mirrorToUse = ""
    mirrorDepth = 0
    for fullUrl in mirrorList:
        # baseUrl = fullUrl.split('://')[1].split('/')[0]
        curlResults = True
        for repo,type in allRepos.items():
            if type == "remote":
                baseUrl = fullUrl.replace('$arch',ARCH).replace('$repo',repo)
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
        
        if curlResults:
            print('Got reponse')

            mirrorToUse = fullUrl
            mirrorDepth = fullUrl.split('/$repo')[0].count('/')-2
            print("Mirror "+mirrorToUse)
            print("Depth "+str(mirrorDepth))
            return {"url":mirrorToUse,"depth":mirrorDepth}
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
           runCommand = 'wget2 -e robots=off -N --no-if-modified-since -P "'+repoRoot+'" -nH -m --cut-dirs='+str(mirrorToUse["depth"])+' --no-parent --timeout=3 --accept="*.pkg.tar*" '+downloadUrl
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

    return threadQueue


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
    
    # Get all the repos and add them to the allRepos dict. with the value being the type of repo it is.
    allRepos=dict.fromkeys(configFile["maint_config"]["remote_repos"],"remote")

    try:
        allRepos.update(dict.fromkeys(configFile["maint_config"]["local_repos"],"local"))
    except:
        print("Local repo not specified")

    MAX_RETRY = 3
    readyToContinue = False
    attempts = 0
    while (not readyToContinue and attempts < MAX_RETRY):
        attempts += 1

        mirrorToUse = getWorkingMirror(configFile=configFile, allRepos=allRepos)
        threadQueue = runDownloadThreads(repoRoot=repoRoot,mirrorToUse=mirrorToUse,allRepos=allRepos)

        addedTotal = 0
        addedPackages = ""
        removedTotal = 0
        removedPackages = ""
        readyToContinue = True

        while not threadQueue.empty():
            result = threadQueue.get()
            addedTotal += result[0]
            addedPackages += result[1]
            removedTotal += result[2]
            removedPackages += result[3]
            if(result[4]):
                readyToContinue = False

    if addedTotal > 0:
        print("New files added - run notify")
        scriptPath = Path(sys.argv[0]).parent.resolve()
        notifyCommand = 'python "'+str(scriptPath)+'/repo_notify.py" -c "'+args["config"]+'" -m "Added '+str(addedTotal)+' new packages.\n' + addedPackages + '"'
        print(notifyCommand)
        subprocess.run(notifyCommand, shell=True)
    
    print("Done")


if __name__ == "__main__":
    main()