# D118-PS-Staff-Sync

Script to take staff info from PowerSchool, create/move/disable Google accounts, add custom schema data to them to enable further automation, etc.  
While I took some steps to make it slightly robust against different building configurations, the script is still highly specific to our district and implementation.  
If you are going to use it in your district please see the requirements and items you will need to change listed below.  

If you would like to employ my help as a consultant to help set this up for your specifc situation, please open an issue in this repository

## Requirements

- Python (create and tested on Python 3.10.6) installed on the machine that is running the script - [Download](https://www.python.org/downloads/release/python-3106/)
- A number of python packages/libraries:
  - oracledb - connects to the PowerSchool database - [Info Link](https://oracle.github.io/python-oracledb/) - `pip install oracledb --upgrade`
  - Google API Python Library - Allows interacting with Google Admin through the API - [Info Link](https://github.com/googleapis/google-api-python-client) - `pip install google-api-python-client`
- Google Cloud Developer Project
  - Go to console.cloud.google.com and walk through setting up a new project. You will need to enable the Admin SDK API, and generate a OAuth 2.0 Client ID
    - Once you generate the OAuth Client, you need to download the .json file and save it as "credentials.json" in the folder the script runs from
    - The first time you run the script, it will pop up a web browser asking you to sign in as an Administrator for your domain and to authorize the scopes it uses. It will then create a token.json file in the script folder that saves the authorization
  - See also the [API Python Library getting started doc](https://github.com/googleapis/google-api-python-client/blob/main/docs/start.md)
- Connection to PowerSchool Server via SQL
  - IP, port, and database name saved as POWERSCHOOL_PROD_DB environment variable
  - Password saved as POWERSCHOOL_DB_PASSWORD environment variable
- Buildings set up with unique names in PS
  - Matching organizational units in Google Admin as Building Name + Staff. Aka "Test School Staff"  
- Google Admin custom schemas set up
  - At minimum, you will need a category named "Synchronization_Data", with attributes as follows:
    - DCID - Whole Number
    - Homeschool ID - Whole Number
    - School Access List - Text
    - Staff Type - Whole Number
    - Staff Group - Whole Number
  - Additionally, we use CrisisGO in our district and therefore the script references a category named "CrisisGO" with Building and CellPhone text attributes.  
  If you do not wish to use this simply edit out any custom schemas referencing CrisisGO in the code.
- Items you will need to edit in order to customize for your district:
  - Change the suspended org unit, currently set to ./Suspended Accounts
  - Change the substitute teacher account org unit, currently set to ./Substitute Teachers
  - Change the umbrella org unit above each school, as it is set to ./D118 Staff/... right now
  - Define any org units you do not want users moved out of, called "frozenOrgs"
  - Define any names of accounts you wish to ignore from PowerSchool, called "badnames". Useful for ignoring test students/teachers
  - A default password for new user accounts saved as the NEW_USER_PASSWORD environment variable
  - The CrisisGO building section under the comment that says `# set the building field for CrisisGO to count certain buildings as the WHS group`  
