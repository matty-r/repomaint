import pycurl
from io import BytesIO
import json
import subprocess
import argparse
import repo_dbmaint
import threading
from pathlib import Path

curl = pycurl.Curl()
b = BytesIO()

# Construct an argument parser
all_args = argparse.ArgumentParser()

def main():
    # Add arguments to the parser
    all_args.add_argument("-r", "--root", required=True,
                        help="Path to the root repo directory which contains the repos /repo/path/")
    args = vars(all_args.parse_args())

    curl.setopt(curl.URL, 'icanhazip.com')
    curl.setopt(curl.WRITEDATA, b)
    curl.perform()
    ipAddress = str(b.getvalue(), 'UTF-8').splitlines()[0]
    curl.setopt(curl.URL, 'http://ip-api.com/json/'+ipAddress)
    curl.perform()
    response = json.loads(str(b.getvalue(), 'UTF-8').splitlines()[1])
    print("Country Code: "+response["countryCode"])
    mirrorListURL = 'https://archlinux.org/mirrorlist/?country='+response["countryCode"]+'&protocol=http&ip_version=4'
    curl.setopt(curl.URL, mirrorListURL)
    curl.perform()
    mirrorList = []
    for line in [i for i in str(b.getvalue(), 'UTF-8').splitlines() if i.__contains__('#Server = ')]:
        mirrorList.append(line.split('#Server = ')[1])

    mirrorToUse = ""
    mirrorDepth = 0
    for fullUrl in mirrorList:
        baseUrl = fullUrl.split('http://')[1].split('/')[0]
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

    repos=["core","community","extra","multilib"]
    arch="x86_64"
    repoRoot=args['root']
    threadList = []

    for repo in repos:
        downloadUrl = mirrorToUse.replace('$arch',arch).replace('$repo',repo)
        databasePath = Path(repoRoot+'/'+downloadUrl.split(baseUrl)[1]+'/'+repo+'.db.tar.gz')
        th = threading.Thread(target=repo_dbmaint.parseDB, args=([databasePath]))
        threadList.append(th)
        downloadCommand = 'wget2 -P "'+repoRoot+'" -nH -m --cut-dirs='+str(mirrorDepth)+' --no-parent --timeout=3 --accept="*.pkg.tar*" '+downloadUrl
        subprocess.run(downloadCommand, shell=True)
        ## add the db creation/parsing to a thread to do it in the background while the rest of the repos are mirrored
        threadList[-1].start()
        print("Launch thread..")
    
    print("Waiting to finish up..")
    for thread in threadList:
        thread.join()

    print("Done")


if __name__ == "__main__":
    main()