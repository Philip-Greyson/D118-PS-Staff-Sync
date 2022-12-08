# Needs the google-api-python-client, google-auth-httplib2 and the google-auth-oauthlib
# pip install --upgrade google-api-python-client google-auth-httplib2 google-auth-oauthlib

from __future__ import print_function

import json
from re import A
from typing import get_type_hints

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# importing module
import oracledb # needed for connection to PowerSchool server (ordcle database)
import sys # needed for  non-scrolling display
import os # needed for environement variable reading
from datetime import *

# setup db connection
un = 'PSNavigator' #PSNavigator is read only, PS is read/write
pw = os.environ.get('POWERSCHOOL_DB_PASSWORD') #the password for the database account
cs = os.environ.get('POWERSCHOOL_PROD_DB') #the IP address, port, and database name to connect to
print("Username: " + str(un) + " |Password: " + str(pw) + " |Server: " + str(cs)) #debug so we can see where oracle is trying to connect to/with

# the password to use for new staff accounts
newPass = os.environ.get('NEW_USER_PASSWORD')
 # the string location of where suspended accounts should end up, change if this is different
suspended_OU = '/Suspended Accounts'
# string location of where where substitute accounts should end up
substitute_OU = '/Substitute Teachers'
# Define a list of sub-OUs in GAdmin where users should not be moved out of. Used for special permissions, apps, licenses, etc
frozenOrgs = ['/Administrators', '/Mail Merge Users', '/Parallels Desktop Users', '/Utility Accounts']
# List of names that some of the dummy/old accounts use so we can ignore them
# badnames = ['USE', 'Training1','Trianing2','Trianing3','Trianing4','Planning','Admin','NURSE','USER', 'USE ', 'TEST', 'TESTTT', 'DO NOT', 'DO', 'NOT', 'TBD', 'LUNCH']
badnames = ['Use', 'Training1','Trianing2','Trianing3','Trianing4','Planning','Admin','Nurse','User', 'Use ', 'Test', 'Testtt', 'Do Not', 'Do', 'Not', 'Tbd', 'Lunch']

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

# define a custom exception class just for use with logging
class badNameException(Exception):
    pass

with oracledb.connect(user=un, password=pw, dsn=cs) as con: # create the connecton to the database
    with con.cursor() as cur:  # start an entry cursor
        with open('StaffLog.txt', 'w') as log:
            startTime = datetime.now()
            startTime = startTime.strftime('%H:%M:%S')
            print(f'Execution started at {startTime}')
            print(f'Execution started at {startTime}', file=log)
            # Start by getting a list of schools from the schools table view to get the school names, numbers, etc for use
            cur.execute('SELECT name, school_number FROM schools')
            schools = cur.fetchall()
            for school in schools:
                # store results in variables mostly just for readability
                schoolName = school[0].title() # convert to title case since some are all caps
                schoolNum = school[1]
                # construct the string for the organization unit in Google Admin from the building name + staff
                orgUnit = '/D118 Staff/' + schoolName + ' Staff'
                if schoolName == 'Substitute': # check and see if our building is the substitute building since they have a different OU then the rest of staff
                    orgUnit = substitute_OU
                print(f'Starting Building: {schoolName} | {schoolNum} | {orgUnit}') # debug
                print(f'Starting Building: {schoolName} | {schoolNum} | {orgUnit}',file=log) # debug
                print('--------------------------------------------------------------------') # debug
                print('--------------------------------------------------------------------',file=log) # debug

                # get the overall user info (non-school specific) for all users in the current school, filtering to only those who have an email filled in to avoid "fake" accounts like test/temp staff
                cur.execute('SELECT dcid, email_addr, first_name, last_name, teachernumber, groupvalue, canchangeschool FROM users WHERE email_addr IS NOT NULL AND homeschoolid = ' + str(schoolNum) + ' ORDER BY dcid DESC')
                users = cur.fetchall()
                for user in users:
                    try: # put each user in their own try block so we can skip them if they have an error
                        enabled = False # set their enabled flag to be false by default, will be set to true later if they have an active school
                        schoolAccess = [] # create empty list for which schools they have access to
                        # store the info in variables for better readability so its obvious what we pass later on
                        uDCID = str(user[0]) # get the unique DCID for that user
                        email = str(user[1]).lower() # convert email in PS to lowercase to ignore any capital letters in it
                        firstName = str(user[2]).title() # convert to title case as PS is all caps
                        lastName = str(user[3]).title() # convert to title case as PS is all caps
                        teacherNum = str(user[4])
                        securityGroup = str(user[5])
                        homeschool = str(schoolNum)
                        cellphone = ' ' # reset cellphone to blank on each user, will be overwritten if present in PS
                        if firstName in badnames or lastName in badnames: # check their first and last names against the list of test/dummy accounts
                            raise badNameException('Found name that matches list of bad names') # raise an exception for them if they have a bad name, which skips the rest of processing

                        ######## if we want to add their admin access buildings to their school access list uncomment next 3 lines
                        # if user[6]: # if they have a CLOB returned for thir can change schools field, we want to conver that to a list
                            # schoolList = str(user[6].read()) # read the CLOB that is returned
                            # schoolAccess = schoolList.split(';') # split up the result by semicolon into our schoolAccess list to get the individual 
                        # print(str(user) + str(schoolAccess)) # debug

                        # next do a query for their schoolstaff entries that are active, they have one per building they have teacher access in with different info
                        cur.execute('SELECT schoolstaff.schoolid, schoolstaff.status, schoolstaff.staffstatus, u_def_ext_schoolstaff.hr_cellphone \
                                    FROM schoolstaff\
                                    LEFT JOIN u_def_ext_schoolstaff\
                                    ON schoolstaff.dcid = u_def_ext_schoolstaff.schoolstaffdcid \
                                    WHERE schoolstaff.users_dcid = ' + uDCID + ' AND schoolstaff.status = 1\
                                    ORDER BY schoolstaff.schoolid')
                        schoolStaff = cur.fetchall()
                        # The first block of this if handles staff who should have active account
                        if schoolStaff: # if they have results from above their google account should be active
                            bodyDict = {} # define empty dict that will hold the update parameters
                            staffType = '2' # reset the staff type for each user in case there is a situation where their home school is disabled, set to staff as default?
                            for schoolEntry in schoolStaff:
                                schoolCode = schoolEntry[0]
                                # print(schoolEntry) # debug
                                if str(schoolCode) not in schoolAccess: # if the current school code is not in their access list, add it
                                    schoolAccess.append(str(schoolCode))
                                if schoolCode == schoolNum: # if the current school entry is their homeschool
                                    staffType = str(schoolEntry[2]) # get the staff type. 0 = Not Assigned, 1 = Teacher, 2 = Staff, 3 = Lunch Staff, 4 = Substitute
                                    cellphone = str(schoolEntry[3]) if schoolEntry[3] else ' ' # get their cellphone from the custom field or just a blank if its null

                            # set the building field for CrisisGO to count certain buildings as the WHS group
                            if homeschool == '0' or homeschool == '131' or homeschool == '133' or homeschool == '134' or homeschool == '135':
                                building = 'Wauconda High School'
                            else:
                                building = schoolName

                            # convert school access list into string separated by semicolons
                            schoolAccessString = ''
                            for entry in schoolAccess:
                                schoolAccessString = schoolAccessString + entry + ';' # append each entry to the string as well as a semicolon as the separator
                            schoolAccessString = schoolAccessString[:-1] # strip out the final character which is a semicolon

                            # next do a query for the user based on their DCID that should be stored in the Synchronization_Data.DCID custom attribute
                            queryString = 'Synchronization_Data.DCID=' + uDCID # construct the query string which looks for the custom Synchronization_Data custom attribute category and the DCID attribute in that category
                            userToUpdate = service.users().list(customer='my_customer', domain='d118.org', maxResults=2, orderBy='email', projection='full', query=queryString).execute() # return a list of at most 2 users who have that 
                            if userToUpdate.get('users'): # if we found a user in Google that matches the user DCID, they already exist and we just want to update any info
                                frozen = False # define a flag for whether they are in a frozen OU, set to false initially

                                # get info from their google account
                                userToUpdateEmail = userToUpdate.get('users')[0].get('primaryEmail').lower() # get the primary email from the google account results just in case its different than what is in PS
                                currentlySuspended = userToUpdate.get('users')[0].get('suspended')
                                currentOU = userToUpdate.get('users')[0].get('orgUnitPath')
                                print(f'User with DCID: {uDCID} already exists under email {userToUpdateEmail}, updating any info')

                                # check to see if the user is enabled in Google, if not add that to the update body
                                if currentlySuspended == True:
                                    bodyDict.update({'suspended': 'False'})
                                
                                # if the email from PowerSchool is not the same as the email of the profile that containst their DCID
                                if userToUpdateEmail != email:
                                    print(f'ACTION: User {firstName} {lastName} - DCID {uDCID} - has had their email change from {userToUpdateEmail} to {email}, will update email and name')
                                    print(f'ACTION: User {firstName} {lastName} - DCID {uDCID} - has had their email change from {userToUpdateEmail} to {email}, will update email and name', file=log)
                                    bodyDict.update({'primaryEmail' : email}) # add the primary email change to the body of the update
                                    bodyDict.update({'name' : {'givenName' : firstName, 'familyName' : lastName}}) # add the name change to the body of the update
                                
                                # Check to see if they are in the correct OU (which is based on home building assignment)
                                if currentOU != orgUnit:
                                    for org in frozenOrgs: # go through our list of "frozen" OU paths which contain a few users with custom settings, licenses, etc
                                        if org in currentOU: # check and see if the frozen OU path is part of the OU they are currently in, if so set the frozen flag to True
                                            frozen = True
                                    if frozen: # if they are in a frozen OU we do not add the change, but just print out an info line for logging
                                        print(f'INFO: User {email} is in the frozen OU {currentOU} and will not be moved to {orgUnit}')
                                        print(f'INFO: User {email} is in the frozen OU {currentOU} and will not be moved to {orgUnit}', file=log)
                                    else: # if theyre not in a frozen OU they will have the orgunit change added to the body of the update
                                        print(f'ACTION: User {email} not in a frozen OU, will to be moved from {currentOU} to {orgUnit}')
                                        print(f'ACTION: User {email} not in a frozen OU, will to be moved from {currentOU} to {orgUnit}', file=log)
                                        bodyDict.update({'orgUnitPath' : orgUnit}) # add OU to body of the update


                                # get custom attributes info from their google profile
                                try: # put the retrieval of the custom data in a try/except block because some accounts might not have the data, which will then need to be added
                                    currentSchool = str(userToUpdate.get('users')[0].get('customSchemas').get('Synchronization_Data').get('Homeschool_ID')) # take the first user's custom schema homeschool id and store it
                                    currentSchoolAccess = str(userToUpdate.get('users')[0].get('customSchemas').get('Synchronization_Data').get('School_Access_List'))
                                    currentStaffType = str(userToUpdate.get('users')[0].get('customSchemas').get('Synchronization_Data').get('Staff_Type'))
                                    currentGroup = str(userToUpdate.get('users')[0].get('customSchemas').get('Synchronization_Data').get('Staff_Group'))
                                    currentTeacherNumber = str(userToUpdate.get('users')[0].get('externalIds')[0].get('value')) # get the built in employee ID number field from google
                                    currentCell = str(userToUpdate.get('users')[0].get('customSchemas').get('CrisisGO').get('CellPhone')) # get CrisisGO current cell #
                                    currentBuilding = str(userToUpdate.get('users')[0].get('customSchemas').get('CrisisGO').get('Building')) # get CrisisGO custom schema building name
                                    # check and see if any of the custom attributes on the profile differ from what is in PS, if so just update all of them at the same time
                                    if (currentSchool != homeschool) or (currentSchoolAccess != schoolAccessString) or (currentStaffType != staffType) or (currentGroup != securityGroup) or (currentTeacherNumber != teacherNum) or (currentCell != cellphone) or (currentBuilding != building):                                      
                                        print(f'ACTION: Updating {email}. Employee ID from {currentTeacherNumber} to {teacherNum}, homeschool ID from {currentSchool} to {homeschool}, school list from {currentSchoolAccess} to {schoolAccessString}, staff type from {currentStaffType} to {staffType}, security group from {currentGroup} to {securityGroup}, cell from {currentCell} to {cellphone}, building from {currentBuilding} to {building}')
                                        print(f'ACTION: Updating {email}. Employee ID from {currentTeacherNumber} to {teacherNum}, homeschool ID from {currentSchool} to {homeschool}, school list from {currentSchoolAccess} to {schoolAccessString}, staff type from {currentStaffType} to {staffType}, security group from {currentGroup} to {securityGroup}, cell from {currentCell} to {cellphone}, building from {currentBuilding} to {building}', file=log)
                                        bodyDict.update({'customSchemas' : {'Synchronization_Data' : {'Homeschool_ID' : homeschool, 'School_Access_List' : schoolAccessString, 'Staff_Type' : int(staffType), 'Staff_Group' : int(securityGroup)} ,
                                                                             'CrisisGO' : {'CellPhone' : cellphone, 'Building' : building}}}) # add each custom attribute to the body of the update
                                        bodyDict.update({'externalIds' : [{'value' : teacherNum, 'type' : 'organization'}]}) # add the teacher number / employeeID field to the body of the update

                                        #### Following is just debug logging to ensure I know why changes are being made
                                        if (currentSchool != homeschool):
                                            print(f'\t Homeschool ID mismatch for {email}', file=log)
                                        if (currentSchoolAccess != schoolAccessString):
                                            print(f'\t School Access List mismatch for {email}', file=log)
                                        if (currentStaffType != staffType):
                                            print(f'\t Staff Type mismatch for {email}', file=log)
                                        if (currentGroup != securityGroup):
                                            print(f'\t Security Group mismatch for {email}', file=log)
                                        if (currentTeacherNumber != teacherNum):
                                            print(f'\t Employee Number mismatch for {email}', file=log)
                                        if (currentCell != cellphone):
                                            print(f'\t Cell mismatch for {email}', file=log)
                                        if (currentBuilding != building):
                                            print(f'\t Building mismatch for {email}', file=log)

                                except Exception as er:
                                    print(f'ERROR: User {email} had no or was missing Synchronization_Data, it will be created: ({er})')
                                    print(f'ERROR: User {email} had no or was missing Synchronization_Data, it will be created: ({er})', file=log)
                                    print(f'ACTION: Updating {email} to employee ID {teacherNum}, homeschool ID {homeschool}, school list {schoolAccessString}, staff type {staffType}, security group {securityGroup}, cell {cellphone}, building {building}')
                                    print(f'ACTION: Updating {email} to employee ID {teacherNum}, homeschool ID {homeschool}, school list {schoolAccessString}, staff type {staffType}, security group {securityGroup}, cell {cellphone}, building {building}', file=log)
                                    bodyDict.update({'customSchemas' : {'Synchronization_Data' : {'Homeschool_ID' : homeschool, 'School_Access_List' : schoolAccessString, 'Staff_Type' : int(staffType), 'Staff_Group' : int(securityGroup)} , 
                                                                        'CrisisGO' : {'CellPhone' : cellphone, 'Building' : building}}}) # add each custom attribute to the body of the update
                                    bodyDict.update({'externalIds' : [{'value' : teacherNum, 'type' : 'organization'}]}) # add the teacher number / employeeID field to the body of the update

                                # Finally, do the actual update of the user profile, using the bodyDict we have constructed in the above sections
                                if bodyDict: # if there is anything in the body dict we want to update. if its empty we skip the update
                                    try:
                                        print(bodyDict) # debug
                                        # print(bodyDict, file=log) # debug
                                        outcome = service.users().update(userKey = userToUpdateEmail, body=bodyDict).execute() # does the actual updating of the user profile
                                    except Exception as er:
                                        print(f'ERROR: cannot update {user} : {er}')
                                        print(f'ERROR: cannot update {user} : {er}', file=log)

                            else: # there is no result for our DCID query, should try to create a new email account
                                print(f'ACTION: User with DCID: {uDCID} does not exist, will need to create them with email: {email}')
                                print(f'ACTION: User with DCID: {uDCID} does not exist, will need to create them with email: {email}', file=log)
                                try:
                                    # define the new user email, name, and all the basic fields
                                    newUser = {'primaryEmail' : email, 'name' : {'givenName' : firstName, 'familyName' : lastName}, 'password' : newPass, 'changePasswordAtNextLogin' : True,
                                            'orgUnitPath' : orgUnit, 'externalIds' : [{'value' : teacherNum, 'type' : 'organization'}],
                                            'customSchemas' : {
                                                'Synchronization_Data' : {'DCID': int(uDCID), 'Homeschool_ID' : homeschool, 'School_Access_List' : schoolAccessString, 'Staff_Type' : int(staffType), 'Staff_Group' : int(securityGroup)},
                                                'CrisisGO' : {'CellPhone' : cellphone, 'Building' : building}}}
                                    outcome = service.users().insert(body=newUser).execute() # does the actual account creation
                                except Exception as er:
                                    print(f'ERROR on user account creation for {email}: {er}')
                                    print(f'ERROR on user account creation for {email}: {er}', file=log)
                            # print(str(user) + str(schoolAccess)) # debug
                        
                        # This else block handles staff who should be inactive/suspended
                        else:
                            print(f'User {email} has no active schools, will be suspended')
                            queryString = 'Synchronization_Data.DCID=' + uDCID # construct the query string which looks for the custom Synchronization_Data custom attribute category and the DCID attribute in that category
                            userToUpdate = service.users().list(customer='my_customer', domain='d118.org', maxResults=2, orderBy='email', projection='full', query=queryString).execute() # return a list of at most 2 users who have that DCID
                            # print(queryResults) # debug
                            if userToUpdate.get('users'): # if we found a user in Google that matches the user DCID, we can suspend their account and move them to the suspended OU 
                                bodyDict = {} # empty dict that will hold the update parameters
                                userToUpdateEmail = userToUpdate.get('users')[0].get('primaryEmail') # get the primary email from the google account results just in case its different than what is in PS
                                # print(userToUpdateEmail) # debug
                                # userToUpdate = service.users().get(userKey=userToUpdateEmail).execute() # return the google account for that email
                                # print(userToUpdate) # debug
                                if userToUpdate.get('users')[0].get('suspended') != True: # check to see if they have been previously suspended, if not we need to do it
                                    print(f'ACTION: Suspending DCID {uDCID} with {email}')
                                    print(f'ACTION: Suspending DCID {uDCID} with {email}', file=log)
                                    bodyDict.update({'suspended' : 'True'}) # add the suspended: True to the body of the update patch
                                if userToUpdate.get('users')[0].get('orgUnitPath') != suspended_OU: # check to see if they are in the proper OU for suspended users
                                    print(f'ACTION: Moving DCID {uDCID} with {email} to suspended OU {suspended_OU}')
                                    print(f'ACTION: Moving DCID {uDCID} with {email} to suspended OU {suspended_OU}', file=log)
                                    bodyDict.update({'orgUnitPath' : suspended_OU}) # add the suspended OU to the org unit path for the update patch
                                
                                # finally do the update (suspend and move) if we have anything in the bodyDict
                                if bodyDict:
                                    print(bodyDict)
                                    # print(bodyDict, file=log)
                                    outcome = service.users().update(userKey = userToUpdateEmail, body=bodyDict).execute() # does the actual updating of the user profile

                                    # Remove the newly suspended user from any groups they were a member of
                                    userGroups = service.groups().list(userKey=userToUpdateEmail).execute().get('groups')
                                    if userGroups:
                                        for group in userGroups:
                                            name = group.get('name')
                                            groupEmail = group.get('email')
                                            print(f'{email} was a member of: {name} - {groupEmail}, they will be removed from the group')
                                            print(f'{email} was a member of: {name} - {groupEmail}, they will be removed from the group',file=log)
                                            service.members().delete(groupKey=groupEmail, memberKey=email).execute()
                                    else:
                                        print(f'Newly suspended account {email} was not in any groups, no removal needed')
                                        print(f'Newly suspended account {email} was not in any groups, no removal needed', file=log)
                                else:
                                    print(f'\t{email} is already suspended in the suspended accounts OU, no update needed')
                            else:
                                print(f'WARNING: Found inactive user DCID {uDCID} without Google account that matches. Should be {email}')
                                print(f'WARNING: Found inactive user DCID {uDCID} without Google account that matches. Should be {email}', file=log)
                    except badNameException as er:
                        print(f'INFO: found user matching name in bad names list {email} - {firstName} {lastName}')
                        print(f'INFO: found user matching name in bad names list {email} - {firstName} {lastName}', file=log)
                    except Exception as er:
                        print(f'ERROR on {user[1]}: {er}')
                        print(f'ERROR on {user[1]}: {er}', file=log)
            endTime = datetime.now()
            endTime = endTime.strftime('%H:%M:%S')
            print(f'Execution ended at {endTime}')
            print(f'Execution ended at {endTime}', file=log)
