import shutil, os.path, json, datetime, re, glob, requests, os
import subprocess as sp

BINTRAY_USER = os.environ["BINTRAY_USER"]
BINTRAY_PASSWORD = os.environ["BINTRAY_PASSWORD"]

INTERNAL_DATE_FORMAT = "%Yw%W"
VERSION_PATTERN = r"<version>(.*)</version>"

INSTALL_ITEMS = ("examples", "matsim", "contribs", "benchmark")
DEPLOY_ITEMS = ("matsim", "contribs")

# Default values
state = {
    "last_release_commit" : "unknown",
    "last_release_date" : "1990w00"
}

# Check if state is there and load it if so
if os.path.exists("state.json"):
    with open("state.json") as f:
        state.update(json.load(f))

# Clean up MATSim
if os.path.exists("matsim"):
    print("Deleting old checkout ...")
    shutil.rmtree("matsim")

# Clone MATSim
sp.check_call(["git", "clone", "--depth", "1", "https://github.com/matsim-org/matsim.git"])

# Find current commit
current_commit = sp.check_output(["git", "rev-parse", "HEAD"], cwd = "matsim").decode("utf-8").strip()

last_release_date = datetime.datetime.strptime(state["last_release_date"], INTERNAL_DATE_FORMAT)
current_date = datetime.datetime.today().strftime(INTERNAL_DATE_FORMAT)

# We neither need a new release if the day has not passed yet, nor if there have
# not been any changes since the last release
if not current_date == last_release_date:
    if not current_commit == state["last_release_commit"]:
        # At this point a new release is requested

        with open("matsim/pom.xml") as f:
            match = re.search(VERSION_PATTERN, f.read())
            current_version = match.group(1)

        if not current_version.endswith("-SNAPSHOT"):
            raise RuntimeError("The commit checked out from gitlab does not include a SNAPSHOT version!")

        updated_version = current_version.replace("-SNAPSHOT", "-" + current_date)

        current_version_string = "<version>%s</version>" % current_version
        updated_version_string = "<version>%s</version>" % updated_version

        print("SNAPSHOT version is:", current_version)
        print("Updated version is:", updated_version)
        print("Current commit is:", current_commit)

        bintray_auth = requests.auth.HTTPBasicAuth(BINTRAY_USER, BINTRAY_PASSWORD)
        result = requests.get("https://api.bintray.com/packages/matsim-eth/matsim/matsim", auth = bintray_auth)

        if not result.status_code == 200:
            raise RuntimeError("Could not get informaton from Bintray")

        result = result.json()

        if not "versions" in result:
            raise RuntimeError("Did not understand Bintray response")

        if updated_version in result["versions"]:
            raise RuntimeError("Bintray already has the proposed release")

        for path in glob.iglob("matsim/**/pom.xml", recursive = True):
            print("Rewriting ", path, "...")
            content = open(path).read().replace(current_version_string, updated_version_string)
            with open(path, "w+") as f: f.write(content)

        # This part can be changed later, when this moves to the official MATSim bintray
        print("Rewriting Bintray URLs...")

        content = open("matsim/matsim/pom.xml").read()
        content = content.replace("https://api.bintray.com/maven/matsim/matsim/matsim", "https://api.bintray.com/maven/matsim-eth/matsim/matsim/")
        with open("matsim/matsim/pom.xml", "w+") as f: f.write(content)

        content = open("matsim/contribs/pom.xml").read()
        content = content.replace("https://api.bintray.com/maven/matsim/matsim/matsim", "https://api.bintray.com/maven/matsim-eth/matsim/matsim/")
        with open("matsim/contribs/pom.xml", "w+") as f: f.write(content)

        print("Installing maven artifacts ...")
        for item in INSTALL_ITEMS:
            sp.check_call([
                "mvn", "install", "--batch-mode", "--fail-at-end",
                "-Dmaven.test.redirectTestOutputToFile",
                "-Dmatsim.preferLocalDtds=true"], cwd = "matsim")

        print("Deploying maven artifacts ...")
        for item in DEPLOY_ITEMS:
            sp.check_call([
                "mvn", "deploy", "--batch-mode", "--fail-at-end",
                "--settings", "../../settings.xml",
                "-Dmaven.test.redirectTestOutputToFile",
                "-Dmatsim.preferLocalDtds=true",
                "-DskipTests=true"], cwd = "matsim/%s" % item)

        print("Publishing artifacts ...")
        result = requests.post("https://api.bintray.com/content/matsim-eth/matsim/matsim/%s/publish" % updated_version, auth = bintray_auth)

        if not result.status_code == 200:
            raise RuntimeError("Problem publishing the package")

        with open("state.json", "w+") as f:
            state["last_release_commit"] = current_commit
            state["last_release_date"] = current_date
            json.dump(state, f)

        print("Published version:", updated_version)
    else:
        print("No changes since last release -> no new release necessary")
else:
    print("You're too early. The day has not passed.")

#
