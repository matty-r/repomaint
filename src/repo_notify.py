import pycurl
import argparse
import json
from pathlib import Path
import sys

# Construct an argument parser
all_args = argparse.ArgumentParser()

def main():
    ##
    # Add arguments to the parser
    whichType = all_args.add_mutually_exclusive_group()
    whichType.required = True
    whichType.add_argument("-c", "--config", required=False,
                        help="Path to the config file which contains the appropriate settings")
    whichType.add_argument("-s", "--service", required=False,
                        help="Name of notification service to use. Requires matching .cfg")
    all_args.add_argument("-m", "--message", required=True,
                        help="Message to send.")
    args = vars(all_args.parse_args())

    if args['config']:
        services = json.load(open(args["config"]))["service_config"]["notifiers"]
        for service in services:
            if service["notifier"]["enabled"]:
                runNotifier(service["notifier"]["type"], args['message'])
    else:
        runNotifier(args['service'], args['message'])

def runNotifier(type: str, message: str):
    if type == "pushover":
        pushOverNotify(message)
    elif type == "email":
        print("not yet implemented")
        print(message)
    else:
        print("nothing matching")
        print("not yet implemented?")

def pushOverNotify(message: str):
    thisPath = str(Path(str(Path(sys.argv[0]).parent.parent.resolve())+"/config/notifiers/pushover.json").resolve())
    pushOverJson = json.load(open(thisPath))
    
    c = pycurl.Curl()
    c.setopt(pycurl.URL, 'https://api.pushover.net/1/messages.json')
    c.setopt(pycurl.HTTPHEADER, ['Accept:application/json'])
    send = [("token", pushOverJson['token']),
            ('user', pushOverJson['user']),
            ('message',message)]
    c.setopt(pycurl.HTTPPOST, send)
    c.perform()
    return 0

if __name__ == "__main__":
    main()