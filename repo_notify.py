import pycurl
import argparse
import json

# Construct an argument parser
all_args = argparse.ArgumentParser()

def main():
    ##
    # Add arguments to the parser
    all_args.add_argument("-s", "--service", required=True,
                        help="Name of notification service to use. Requires matching .cfg")
    all_args.add_argument("-m", "--message", required=True,
                        help="Message to send.")
    args = vars(all_args.parse_args())

    if args['service'] == "pushover":
        pushOverNotify(args['message'])


def pushOverNotify(message: str):
    pushOverJson = json.load(open('pushover.cfg'))
    
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