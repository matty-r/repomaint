import sys, os
from pathlib import Path
import json

## Deployable files/Folder structure
configBasePath = "/config.json"



thisPath = Path(sys.argv[0]).resolve()
filesRoot = Path(str(thisPath.parent.parent)).resolve()
configFilePath = Path(str(filesRoot)+'/config.json').resolve()
configFile = json.load(open(configFilePath))
serviceFilePath = Path(str(filesRoot)+'/services/repomaint.service').resolve()
timerFilePath = serviceFilePath = Path(str(filesRoot)+'/services/repomaint.timer').resolve()
repoRoot = configFile["maint_config"]["repo_root"]