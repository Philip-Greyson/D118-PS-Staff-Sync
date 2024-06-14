"""Script to Google profile information for staff from PowerSchool.

https://github.com/Philip-Greyson/D118-PS-Staff-Sync

Needs the google-api-python-client, google-auth-httplib2 and the google-auth-oauthlib:
pip install --upgrade google-api-python-client google-auth-httplib2 google-auth-oauthlib
also needs oracledb: pip install oracledb --upgrade
"""


import os  # needed for environement variable reading
import sys  # needed for  non-scrolling display
from datetime import *
from re import A
from typing import get_type_hints

# importing module
import oracledb  # needed for connection to PowerSchool server (ordcle database)
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# setup db connection
DB_UN = os.environ.get('POWERSCHOOL_READ_USER')  # username for read-only database user
DB_PW = os.environ.get('POWERSCHOOL_DB_PASSWORD')  # the password for the database account
DB_CS = os.environ.get('POWERSCHOOL_PROD_DB')  # the IP address, port, and database name to connect to
print(f"Database Username: {DB_UN} |Password: {DB_PW} |Server: {DB_CS}")  # debug so we can see where oracle is trying to connect to/with


NEW_PASSWORD = os.environ.get('NEW_USER_PASSWORD')  # the password to use for new staff accounts
OU_PREFIX = '/D118 Staff/'  # the umbrella OU that all staff members are inside of except suspended or subs
BUILDING_OU_SUFFIX = ' Staff'  # the suffix after the building name for staff OUs
SUSPENDED_OU = '/Suspended Accounts'  # the string location of where suspended accounts should end up, change if this is different
SUBSTITUTE_OU = '/Substitute Teachers'  # string location of where where substitute accounts should end up
SUB_BUILDING_NAME = 'Substitute'  # name of the substitute building in PowerSchool
FROZEN_OUS = ['/Administrators', '/Mail Merge Users', '/Parallels Desktop Users', '/Utility Accounts']  # Define a list of sub-OUs in GAdmin where users should not be moved out of. Used for special permissions, apps, licenses, etc
BAD_NAMES = ['use', 'training1','trianing2','trianing3','trianing4','planning','admin','nurse','user','use ','test','testtt','do not','do','not','tbd','lunch','new','teacher','new teacher','teacher-1','sub','substitute','plugin','mba','tech','technology','administrator']  # List of names that some of the dummy/old accounts use so we can ignore them

REMOVE_SUSPENDED_FROM_GROUPS = True  # boolean flag to control whether newly suspended accounts should be removed from all email groups when they get suspended
SKIP_NUMERIC_EMAILS = True  # boolean flag to control whether all numeric emails should be skipped

GOOGLE_DOMAIN = 'd118.org'  # domain for google admin user searches
# At least one custom attribute is needed to match the powerschool DCID to google account. The custom attribute category and field name are listed below
CUSTOM_ATTRIBUTE_SYNC_CATEGORY = 'Synchronization_Data'  # the category name that the custom attributes will be in
CUSTOM_ATTRIBUTE_DCID = 'DCID'  # field name for the dcid custom attribute in the sync category
CUSTOM_ATTRIBUTE_ID = 'Teacher-Number'  # field name for the ID# / Teacher # custom attribute in the sync category

# I also use other custom attributes for a number of things including which schools they should have access to which is used for email groups, staff types and security groups, etc
USE_EXTRA_CUSTOM_ATTRIBUTES = True  # boolean flag for whether we are using all the custom attributes listed below
CUSTOM_ATTRIBUTE_SCHOOL = 'Homeschool_ID'  # the field name for the homeschool id custom attribute in the sync category
CUSTOM_ATTRIBUTE_ACCESS_LIST = 'School_Access_List'  # field name for the school access list custom attribute in the sync category
CUSTOM_ATTRIBUTE_TYPE = 'Staff_Type'  # field name for the staff type custom attribute in the sync category
CUSTOM_ATTRIBUTE_GROUP = 'Staff_Group'  # field name for the staff group custom attribute in the sync category
CUSTOM_ATTRIBUTE_CRISISGO_CATEGORY = 'CrisisGO'  # category name for the crisisGo custom attributes
CUSTOM_ATTRIBUTE_CELL = 'CellPhone'  # field name for the crisisGo cellphone custom attribute
CUSTOM_ATTRIBUTE_BUILDING = 'Building'  # field name for the crisisGo building custom attribute

# Google API Scopes that will be used. If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/admin.directory.user', 'https://www.googleapis.com/auth/admin.directory.group', 'https://www.googleapis.com/auth/admin.directory.group.member', 'https://www.googleapis.com/auth/admin.directory.orgunit', 'https://www.googleapis.com/auth/admin.directory.userschema']

# Get credentials from json file, ask for permissions on scope or use existing token.json approval, then build the "service" connection to Google API
creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
if os.path.exists('token.json'):
    creds = Credentials.from_authorized_user_file('token.json', SCOPES)
# If there are no (valid) credentials available, let the user log in.
if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file(
            'credentials.json', SCOPES)
        creds = flow.run_local_server(port=0)
    # Save the credentials for the next run
    with open('token.json', 'w') as token:
        token.write(creds.to_json())

service = build('admin', 'directory_v1', credentials=creds)

class BadNameExceptionError(Exception):
    """Just a custom exception class for use with logging."""

    pass

class NumericEmailExceptionError(Exception):
    """Custom exception class for numeric emails, for use with logging."""

    pass

if __name__ == '__main__':  # main file execution
    with open('StaffLog.txt', 'w') as log:
        startTime = datetime.now()
        startTime = startTime.strftime('%H:%M:%S')
        print(f'INFO: Execution started at {startTime}')
        print(f'INFO: Execution started at {startTime}', file=log)
        with oracledb.connect(user=DB_UN, password=DB_PW, dsn=DB_CS) as con:  # create the connecton to the database
            with con.cursor() as cur:  # start an entry cursor
                print(f'INFO: Connection established to PS database on version: {con.version}')
                print(f'INFO: Connection established to PS database on version: {con.version}', file=log)

                # Start by getting a list of schools from the schools table view to get the school names, numbers, etc for use
                cur.execute('SELECT name, school_number FROM schools')
                schools = cur.fetchall()
                for school in schools:
                    # store results in variables mostly just for readability
                    schoolName = school[0].title()  # convert to title case since some are all caps
                    schoolNum = school[1]
                    # construct the string for the organization unit in Google Admin from the building name + staff
                    buildingOrgUnit = OU_PREFIX + schoolName + BUILDING_OU_SUFFIX
                    if schoolName == SUB_BUILDING_NAME:  # check and see if our building is the substitute building since they have a different OU then the rest of staff
                        buildingOrgUnit = SUBSTITUTE_OU
                    print(f'DBUG: Starting Building: {schoolName} | {schoolNum} | {buildingOrgUnit}')  # debug
                    print(f'DBUG: Starting Building: {schoolName} | {schoolNum} | {buildingOrgUnit}',file=log)  # debug

                    # get the overall user info (non-school specific) for all users in the current school, filtering to only those who have an email filled in to avoid "fake" accounts like test/temp staff
                    cur.execute('SELECT users.dcid, users.email_addr, users.first_name, users.last_name, users.teachernumber, users.groupvalue, users.canchangeschool, u_humanresources.cellphone\
                        FROM users LEFT JOIN u_humanresources ON users.dcid = u_humanresources.usersdcid\
                            WHERE users.email_addr IS NOT NULL AND users.homeschoolid = :school ORDER BY users.dcid DESC', school=schoolNum)
                    users = cur.fetchall()
                    for user in users:
                        try:  # put each user in their own try block so we can skip them if they have an error
                            targetOrgUnit = buildingOrgUnit  # set the target OU back to the building default
                            enabled = False  # set their enabled flag to be false by default, will be set to true later if they have an active school
                            schoolAccess = []  # create empty list for which schools they have access to
                            # store the info in variables for better readability so its obvious what we pass later on
                            uDCID = str(user[0])  # get the unique DCID for that user
                            email = str(user[1]).lower()  # convert email in PS to lowercase to ignore any capital letters in it
                            firstName = str(user[2]).title()  # convert to title case as PS is all caps
                            lastName = str(user[3]).title()  # convert to title case as PS is all caps
                            teacherNum = str(user[4])
                            securityGroup = str(user[5])
                            homeschool = str(schoolNum)
                            cellphone = str(user[7]) if user[7] else ''  # set cell phone to blank string if not present in PS
                            if firstName.lower() in BAD_NAMES or lastName.lower() in BAD_NAMES:  # check their first and last names against the list of test/dummy accounts
                                raise BadNameExceptionError('Found name that matches list of bad names')  # raise an exception for them if they have a bad name, which skips the rest of processing
                            if SKIP_NUMERIC_EMAILS:
                                if email.split('@')[0].isnumeric():  # if the part of the email before the domain is all numeric, it is probably a student worker which we want to skip as they will already exist
                                    raise NumericEmailExceptionError('Found email which is all numbers, skipping them')  # raise an exception for them, which skips the rest of their processing

                            ######## if we want to add their admin access buildings to their school access list uncomment next 3 lines
                            # if user[6]: # if they have a CLOB returned for thir can change schools field, we want to conver that to a list
                                # schoolList = str(user[6].read()) # read the CLOB that is returned
                                # schoolAccess = schoolList.split(';') # split up the result by semicolon into our schoolAccess list to get the individual
                            # print(str(user) + str(schoolAccess)) # debug

                            # next do a query for their schoolstaff entries that are active, they have one per building they have teacher access in with different info
                            cur.execute('SELECT schoolid, status, staffstatus FROM schoolstaff WHERE users_dcid = :dcid AND status = 1 ORDER BY schoolid', dcid=uDCID)
                            schoolStaff = cur.fetchall()
                            # The first block of this if handles staff who should have active account
                            if schoolStaff:  # if they have results from above their google account should be active
                                bodyDict = {}  # define empty dict that will hold the update parameters
                                staffType = '2'  # reset the staff type for each user in case there is a situation where their home school is disabled, set to staff as default?
                                for schoolEntry in schoolStaff:
                                    schoolCode = schoolEntry[0]
                                    # print(schoolEntry) # debug
                                    if str(schoolCode) not in schoolAccess:  # if the current school code is not in their access list, add it
                                        schoolAccess.append(str(schoolCode))
                                    if schoolCode == schoolNum:  # if the current school entry is their homeschool
                                        staffType = str(schoolEntry[2])  # get the staff type. 0 = Not Assigned, 1 = Teacher, 2 = Staff, 3 = Lunch Staff, 4 = Substitute
                                        # print(f'DEBUG: {firstName} {lastName} Staff type: {staffType}')
                                        if staffType == "4":  # if they have a staff type of sub, we want to override their target OU to put them in the sub OU even if they are a long term sub in a building
                                            # print(f'---------------DEBUG: {firstName} {lastName} Should be in the SUB OU--------------')
                                            # print(f'---------------DEBUG: {firstName} {lastName} Should be in the SUB OU--------------',file=log)
                                            targetOrgUnit = SUBSTITUTE_OU

                                if USE_EXTRA_CUSTOM_ATTRIBUTES:
                                    # set the building field for CrisisGO to count certain buildings as the WHS group
                                    if homeschool == '0' or homeschool == '131' or homeschool == '133' or homeschool == '134' or homeschool == '135':
                                        building = 'Wauconda High School'
                                    else:
                                        building = schoolName

                                # convert school access list into string separated by semicolons
                                schoolAccessString = ''
                                for entry in schoolAccess:
                                    schoolAccessString = schoolAccessString + entry + ';'  # append each entry to the string as well as a semicolon as the separator
                                schoolAccessString = schoolAccessString[:-1]  # strip out the final character which is a semicolon

                                # next do a query for the user based on their DCID that should be stored in the Synchronization_Data.DCID custom attribute
                                queryString = CUSTOM_ATTRIBUTE_SYNC_CATEGORY + '.' + CUSTOM_ATTRIBUTE_DCID + '=' + uDCID  # construct the query string which looks for the custom Synchronization_Data custom attribute category and the DCID attribute in that category
                                userToUpdate = service.users().list(customer='my_customer', domain=GOOGLE_DOMAIN, maxResults=2, orderBy='email', projection='full', query=queryString).execute()  # return a list of at most 2 users who have that
                                if userToUpdate.get('users'):  # if we found a user in Google that matches the user DCID, they already exist and we just want to update any info
                                    frozen = False  # define a flag for whether they are in a frozen OU, set to false initially

                                    # get info from their google account
                                    userToUpdateEmail = userToUpdate.get('users')[0].get('primaryEmail').lower()  # get the primary email from the google account results just in case its different than what is in PS
                                    currentlySuspended = userToUpdate.get('users')[0].get('suspended')
                                    currentOU = userToUpdate.get('users')[0].get('orgUnitPath')
                                    print(f'DBUG: User with DCID: {uDCID} already exists under email {userToUpdateEmail}, updating any info')
                                    print(f'DBUG: User with DCID: {uDCID} already exists under email {userToUpdateEmail}, updating any info', file=log)

                                    # check to see if the user is enabled in Google, if not add that to the update body
                                    if currentlySuspended == True:
                                        print(f'INFO: User {email} - DCID {uDCID} - is currently suspended and will be re-enabled')
                                        print(f'INFO: User {email} - DCID {uDCID} - is currently suspended and will be re-enabled', file=log)
                                        bodyDict.update({'suspended': False})

                                    # if the email from PowerSchool is not the same as the email of the profile that containst their DCID
                                    if userToUpdateEmail != email:
                                        print(f'INFO: User {firstName} {lastName} - DCID {uDCID} - has had their email change from {userToUpdateEmail} to {email}, will update email and name')
                                        print(f'INFO: User {firstName} {lastName} - DCID {uDCID} - has had their email change from {userToUpdateEmail} to {email}, will update email and name', file=log)
                                        bodyDict.update({'primaryEmail' : email})  # add the primary email change to the body of the update
                                        bodyDict.update({'name' : {'givenName' : firstName, 'familyName' : lastName}})  # add the name change to the body of the update

                                    # Check to see if they are in the correct OU (which is based on home building assignment)
                                    if currentOU != targetOrgUnit:
                                        for org in FROZEN_OUS:  # go through our list of "frozen" OU paths which contain a few users with custom settings, licenses, etc
                                            if org in currentOU:  # check and see if the frozen OU path is part of the OU they are currently in, if so set the frozen flag to True
                                                frozen = True
                                        if frozen:  # if they are in a frozen OU we do not add the change, but just print out an info line for logging
                                            print(f'INFO: User {email} is in the frozen OU {currentOU} and will not be moved to {targetOrgUnit}')
                                            print(f'INFO: User {email} is in the frozen OU {currentOU} and will not be moved to {targetOrgUnit}', file=log)
                                        else:  # if theyre not in a frozen OU they will have the targetOrgUnit change added to the body of the update
                                            print(f'INFO: User {email} not in a frozen OU, will to be moved from {currentOU} to {targetOrgUnit}')
                                            print(f'INFO: User {email} not in a frozen OU, will to be moved from {currentOU} to {targetOrgUnit}', file=log)
                                            bodyDict.update({'orgUnitPath' : targetOrgUnit})  # add OU to body of the update


                                    if USE_EXTRA_CUSTOM_ATTRIBUTES:  # get custom attributes info from their google profile if true
                                        try:  # put the retrieval of the custom data in a try/except block because some accounts might not have the data, which will then need to be added
                                            currentSchool = str(userToUpdate.get('users')[0].get('customSchemas').get(CUSTOM_ATTRIBUTE_SYNC_CATEGORY).get(CUSTOM_ATTRIBUTE_SCHOOL))  # take the first user's custom schema homeschool id and store it
                                            currentSchoolAccess = str(userToUpdate.get('users')[0].get('customSchemas').get(CUSTOM_ATTRIBUTE_SYNC_CATEGORY).get(CUSTOM_ATTRIBUTE_ACCESS_LIST))
                                            currentStaffType = str(userToUpdate.get('users')[0].get('customSchemas').get(CUSTOM_ATTRIBUTE_SYNC_CATEGORY).get(CUSTOM_ATTRIBUTE_TYPE))
                                            currentGroup = str(userToUpdate.get('users')[0].get('customSchemas').get(CUSTOM_ATTRIBUTE_SYNC_CATEGORY).get(CUSTOM_ATTRIBUTE_GROUP))
                                            currentTeacherNumber = str(userToUpdate.get('users')[0].get('externalIds')[0].get('value'))  # get the built in employee ID number field from google
                                            currentCustomTeacherNumber = str(userToUpdate.get('users')[0].get('customSchemas').get(CUSTOM_ATTRIBUTE_SYNC_CATEGORY).get(CUSTOM_ATTRIBUTE_ID))  # get the custom ID number field
                                            currentCell = str(userToUpdate.get('users')[0].get('customSchemas').get(CUSTOM_ATTRIBUTE_CRISISGO_CATEGORY).get(CUSTOM_ATTRIBUTE_CELL))  # get CrisisGO current cell #
                                            currentBuilding = str(userToUpdate.get('users')[0].get('customSchemas').get(CUSTOM_ATTRIBUTE_CRISISGO_CATEGORY).get(CUSTOM_ATTRIBUTE_BUILDING))  # get CrisisGO custom schema building name
                                            # check and see if any of the custom attributes on the profile differ from what is in PS, if so just update all of them at the same time
                                            if (currentSchool != homeschool) or (currentSchoolAccess != schoolAccessString) or (currentStaffType != staffType) or (currentGroup != securityGroup) or (currentTeacherNumber != teacherNum) or (currentCustomTeacherNumber != teacherNum) or (currentCell != cellphone) or (currentBuilding != building):
                                                print(f'INFO: Updating {email}. Employee ID from {currentTeacherNumber} to {teacherNum}, homeschool ID from {currentSchool} to {homeschool}, school list from {currentSchoolAccess} to {schoolAccessString}, staff type from {currentStaffType} to {staffType}, security group from {currentGroup} to {securityGroup}, cell from {currentCell} to {cellphone}, building from {currentBuilding} to {building}')
                                                print(f'INFO: Updating {email}. Employee ID from {currentTeacherNumber} to {teacherNum}, homeschool ID from {currentSchool} to {homeschool}, school list from {currentSchoolAccess} to {schoolAccessString}, staff type from {currentStaffType} to {staffType}, security group from {currentGroup} to {securityGroup}, cell from {currentCell} to {cellphone}, building from {currentBuilding} to {building}', file=log)
                                                bodyDict.update({'customSchemas' : {CUSTOM_ATTRIBUTE_SYNC_CATEGORY : {CUSTOM_ATTRIBUTE_SCHOOL : homeschool, CUSTOM_ATTRIBUTE_ACCESS_LIST : schoolAccessString, CUSTOM_ATTRIBUTE_TYPE : int(staffType), CUSTOM_ATTRIBUTE_GROUP : int(securityGroup), CUSTOM_ATTRIBUTE_ID: int(teacherNum)} ,
                                                                                    CUSTOM_ATTRIBUTE_CRISISGO_CATEGORY : {CUSTOM_ATTRIBUTE_CELL : cellphone, CUSTOM_ATTRIBUTE_BUILDING : building}}})  # add each custom attribute to the body of the update
                                                bodyDict.update({'externalIds' : [{'value' : teacherNum, 'type' : 'organization'}]})  # add the teacher number / employeeID field to the body of the update

                                                #### Following is just debug logging to ensure I know why changes are being made
                                                if (currentSchool != homeschool):
                                                    print(f'DBUG: Homeschool ID mismatch for {email}')
                                                    print(f'DBUG: Homeschool ID mismatch for {email}', file=log)
                                                if (currentSchoolAccess != schoolAccessString):
                                                    print(f'DBUG: School Access List mismatch for {email}')
                                                    print(f'DBUG: School Access List mismatch for {email}', file=log)
                                                if (currentStaffType != staffType):
                                                    print(f'DBUG: Staff Type mismatch for {email}')
                                                    print(f'DBUG: Staff Type mismatch for {email}', file=log)
                                                if (currentGroup != securityGroup):
                                                    print(f'DBUG:Security Group mismatch for {email}')
                                                    print(f'DBUG:Security Group mismatch for {email}', file=log)
                                                if (currentTeacherNumber != teacherNum) or (currentCustomTeacherNumber != teacherNum):
                                                    print(f'DBUG: Employee Number mismatch for {email}')
                                                    print(f'DBUG: Employee Number mismatch for {email}', file=log)
                                                if (currentCell != cellphone):
                                                    print(f'DBUG: Cell mismatch for {email}')
                                                    print(f'DBUG: Cell mismatch for {email}', file=log)
                                                if (currentBuilding != building):
                                                    print(f'DBUG: Building mismatch for {email}')
                                                    print(f'DBUG: Building mismatch for {email}', file=log)

                                        except Exception as er:
                                            print(f'ERROR: User {email} had no or was missing Synchronization_Data, it will be created: ({er})')
                                            print(f'ERROR: User {email} had no or was missing Synchronization_Data, it will be created: ({er})', file=log)
                                            print(f'INFO: Updating {email} to employee ID {teacherNum}, homeschool ID {homeschool}, school list {schoolAccessString}, staff type {staffType}, security group {securityGroup}, cell {cellphone}, building {building}')
                                            print(f'INFO: Updating {email} to employee ID {teacherNum}, homeschool ID {homeschool}, school list {schoolAccessString}, staff type {staffType}, security group {securityGroup}, cell {cellphone}, building {building}', file=log)
                                            bodyDict.update({'customSchemas' : {CUSTOM_ATTRIBUTE_SYNC_CATEGORY : {CUSTOM_ATTRIBUTE_SCHOOL : homeschool, CUSTOM_ATTRIBUTE_ACCESS_LIST : schoolAccessString, CUSTOM_ATTRIBUTE_TYPE : int(staffType), CUSTOM_ATTRIBUTE_GROUP : int(securityGroup)} ,
                                                                                CUSTOM_ATTRIBUTE_CRISISGO_CATEGORY : {CUSTOM_ATTRIBUTE_CELL : cellphone, CUSTOM_ATTRIBUTE_BUILDING : building}}})  # add each custom attribute to the body of the update
                                            bodyDict.update({'externalIds' : [{'value' : teacherNum, 'type' : 'organization'}]})  # add the teacher number / employeeID field to the body of the update

                                    # Finally, do the actual update of the user profile, using the bodyDict we have constructed in the above sections
                                    if bodyDict:  # if there is anything in the body dict we want to update. if its empty we skip the update
                                        try:
                                            print(f'DBUG: {bodyDict}')  # debug
                                            # print(bodyDict, file=log) # debug
                                            outcome = service.users().update(userKey = userToUpdateEmail, body=bodyDict).execute()  # does the actual updating of the user profile

                                        # error catching for new account creation
                                        except HttpError as er:   # catch Google API http errors, get the specific message and reason from them for better logging
                                            status = er.status_code
                                            details = er.error_details[0]  # error_details returns a list with a dict inside of it, just strip it to the first dict
                                            print(f'ERROR {status} from Google API on user account update for {email}: {details["message"]}. Reason: {details["reason"]}')
                                            print(f'ERROR {status} from Google API on user account update for {email}: {details["message"]}. Reason: {details["reason"]}', file=log)
                                        except Exception as er:
                                            print(f'ERROR: cannot update {email} : {er}')
                                            print(f'ERROR: cannot update {email} : {er}', file=log)

                                else:  # there is no result for our DCID query, should try to create a new email account
                                    print(f'INFO: User with DCID: {uDCID} does not exist, will need to create them with email: {email}')
                                    print(f'INFO: User with DCID: {uDCID} does not exist, will need to create them with email: {email}', file=log)
                                    try:
                                        if USE_EXTRA_CUSTOM_ATTRIBUTES:
                                            # define the new user email, name, and all the basic fields as well as all custom attributes
                                            newUser = {'primaryEmail' : email, 'name' : {'givenName' : firstName, 'familyName' : lastName}, 'password' : NEW_PASSWORD, 'changePasswordAtNextLogin' : True,
                                                    'orgUnitPath' : targetOrgUnit, 'externalIds' : [{'value' : teacherNum, 'type' : 'organization'}],
                                                    'customSchemas' : {
                                                        CUSTOM_ATTRIBUTE_SYNC_CATEGORY : {'DCID': int(uDCID), CUSTOM_ATTRIBUTE_SCHOOL : homeschool, CUSTOM_ATTRIBUTE_ACCESS_LIST : schoolAccessString, CUSTOM_ATTRIBUTE_TYPE : int(staffType), CUSTOM_ATTRIBUTE_GROUP : int(securityGroup)},
                                                        CUSTOM_ATTRIBUTE_CRISISGO_CATEGORY : {CUSTOM_ATTRIBUTE_CELL : cellphone, CUSTOM_ATTRIBUTE_BUILDING : building}}}
                                        else:
                                            # define the new user email, name, and all the basic fields and only the sync dcid custom attribute
                                            newUser = {'primaryEmail' : email, 'name' : {'givenName' : firstName, 'familyName' : lastName}, 'password' : NEW_PASSWORD, 'changePasswordAtNextLogin' : True,
                                                    'orgUnitPath' : targetOrgUnit, 'externalIds' : [{'value' : teacherNum, 'type' : 'organization'}],
                                                    'customSchemas' : {CUSTOM_ATTRIBUTE_SYNC_CATEGORY : {'DCID': int(uDCID)}}}
                                        outcome = service.users().insert(body=newUser).execute()  # does the actual account creation

                                    # error catching for new account creation
                                    except HttpError as er:   # catch Google API http errors, get the specific message and reason from them for better logging
                                        status = er.status_code
                                        details = er.error_details[0]  # error_details returns a list with a dict inside of it, just strip it to the first dict
                                        print(f'ERROR {status} from Google API on user account creation for {email}: {details["message"]}. Reason: {details["reason"]}')
                                        print(f'ERROR {status} from Google API on user account creation for {email}: {details["message"]}. Reason: {details["reason"]}', file=log)
                                    except Exception as er:
                                        print(f'ERROR on user account creation for {email}: {er}')
                                        print(f'ERROR on user account creation for {email}: {er}', file=log)
                                # print(str(user) + str(schoolAccess)) # debug

                            # This else block handles staff who should be inactive/suspended
                            else:
                                print(f'DBUG: User {email} has no active schools and should be suspended')
                                queryString = CUSTOM_ATTRIBUTE_SYNC_CATEGORY + '.' + CUSTOM_ATTRIBUTE_DCID + '=' + uDCID  # construct the query string which looks for the custom Synchronization_Data custom attribute category and the DCID attribute in that category
                                userToUpdate = service.users().list(customer='my_customer', domain=GOOGLE_DOMAIN, maxResults=2, orderBy='email', projection='full', query=queryString).execute()  # return a list of at most 2 users who have that DCID
                                # print(queryResults) # debug
                                if userToUpdate.get('users'):  # if we found a user in Google that matches the user DCID, we can suspend their account and move them to the suspended OU
                                    bodyDict = {}  # empty dict that will hold the update parameters
                                    userToUpdateEmail = userToUpdate.get('users')[0].get('primaryEmail')  # get the primary email from the google account results just in case its different than what is in PS
                                    # print(userToUpdateEmail) # debug
                                    # print(userToUpdate) # debug
                                    if userToUpdate.get('users')[0].get('suspended') != True:  # check to see if they have been previously suspended, if not we need to do it
                                        print(f'INFO: Suspending DCID {uDCID} with {email}')
                                        print(f'INFO: Suspending DCID {uDCID} with {email}', file=log)
                                        bodyDict.update({'suspended' : True})  # add the suspended: True to the body of the update patch
                                    if userToUpdate.get('users')[0].get('orgUnitPath') != SUSPENDED_OU:  # check to see if they are in the proper OU for suspended users
                                        print(f'INFO: Moving DCID {uDCID} with {email} to suspended OU {SUSPENDED_OU}')
                                        print(f'INFO: Moving DCID {uDCID} with {email} to suspended OU {SUSPENDED_OU}', file=log)
                                        bodyDict.update({'orgUnitPath' : SUSPENDED_OU})  # add the suspended OU to the org unit path for the update patch

                                    # finally do the update (suspend and move) if we have anything in the bodyDict
                                    if bodyDict:
                                        try:
                                            print(bodyDict)
                                            # print(bodyDict, file=log)
                                            outcome = service.users().update(userKey = userToUpdateEmail, body=bodyDict).execute()  # does the actual updating of the user profile
                                        # error catching for suspending and move user process
                                        except HttpError as er:   # catch Google API http errors, get the specific message and reason from them for better logging
                                            status = er.status_code
                                            details = er.error_details[0]  # error_details returns a list with a dict inside of it, just strip it to the first dict
                                            print(f'ERROR {status} from Google API while suspending and moving {email} to suspended OU: {details["message"]}. Reason: {details["reason"]}')
                                            print(f'ERROR {status} from Google API while suspending and moving {email} to suspended OU: {details["message"]}. Reason: {details["reason"]}', file=log)
                                        except Exception as er:
                                            print(f'ERROR while processing {email}: {er}')
                                            print(f'ERROR while processing {email}: {er}', file=log)

                                        if REMOVE_SUSPENDED_FROM_GROUPS:  # Remove the newly suspended user from any groups they were a member of
                                            userGroups = service.groups().list(userKey=userToUpdateEmail).execute().get('groups')
                                            if userGroups:
                                                for group in userGroups:
                                                    try:
                                                        name = group.get('name')
                                                        groupEmail = group.get('email')
                                                        print(f'INFO: {email} was a member of: {name} - {groupEmail}, they will be removed from the group')
                                                        print(f'INFO: {email} was a member of: {name} - {groupEmail}, they will be removed from the group',file=log)
                                                        service.members().delete(groupKey=groupEmail, memberKey=email).execute()
                                                    # error catching for removal from group
                                                    except HttpError as er:   # catch Google API http errors, get the specific message and reason from them for better logging
                                                        status = er.status_code
                                                        details = er.error_details[0]  # error_details returns a list with a dict inside of it, just strip it to the first dict
                                                        print(f'ERROR {status} from Google API while removing suspended user {email} from group {groupEmail}: {details["message"]}. Reason: {details["reason"]}')
                                                        print(f'ERROR {status} from Google API while removing suspended user {email} from group {groupEmail}: {details["message"]}. Reason: {details["reason"]}', file=log)
                                                    except Exception as er:
                                                        print(f'ERROR while processing {email}: {er}')
                                                        print(f'ERROR while processing {email}: {er}', file=log)
                                            else:
                                                print(f'DBUG: Newly suspended account {email} was not in any groups, no removal needed')
                                                print(f'DBUG: Newly suspended account {email} was not in any groups, no removal needed', file=log)
                                    else:  # if there is nothing in the body dict (update call) it means they are already suspended and in the right OU
                                        print(f'DBUG: {email} is already suspended and in the suspended accounts OU, no update needed')
                                # if we dont find a user in Google that matches the DCID, but they are supposed to be suspended/inactive, we dont really care so just print a warning
                                else:
                                    print(f'WARN: Found inactive user DCID {uDCID} without Google account that matches. Should be {email}')
                                    print(f'WARN: Found inactive user DCID {uDCID} without Google account that matches. Should be {email}', file=log)


                        # error catching for overall program not caught by other specific catches
                        except BadNameExceptionError:
                            print(f'WARN: Found user matching name in bad names list {email} - {firstName} {lastName}')
                            print(f'WARN: Found user matching name in bad names list {email} - {firstName} {lastName}', file=log)
                        except NumericEmailExceptionError:
                            print(f'WARN: Found user with an all numeric email. DCID: {uDCID} - {firstName} {lastName} - {email}')
                            print(f'WARN: Found user with an all numeric email. DCID: {uDCID} - {firstName} {lastName} - {email}', file=log)
                        except HttpError as er:   # catch Google API http errors, get the specific message and reason from them for better logging
                            status = er.status_code
                            details = er.error_details[0]  # error_details returns a list with a dict inside of it, just strip it to the first dict
                            print(f'ERROR {status} from Google API while processing {user[1]}: {details["message"]}. Reason: {details["reason"]}')
                            print(f'ERROR {status} from Google API while processing {user[1]}: {details["message"]}. Reason: {details["reason"]}', file=log)
                        except Exception as er:
                            print(f'ERROR while processing {user[1]}: {er}')
                            print(f'ERROR while processing {user[1]}: {er}', file=log)
        endTime = datetime.now()
        endTime = endTime.strftime('%H:%M:%S')
        print(f'INFO: Execution ended at {endTime}')
        print(f'INFO: Execution ended at {endTime}', file=log)
