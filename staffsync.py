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
import pysftp # needed for sftp file upload
from datetime import *

# setup db connection
un = 'PSNavigator' #PSNavigator is read only, PS is read/write
pw = os.environ.get('POWERSCHOOL_DB_PASSWORD') #the password for the database account
cs = os.environ.get('POWERSCHOOL_PROD_DB') #the IP address, port, and database name to connect to
print("Username: " + str(un) + " |Password: " + str(pw) + " |Server: " + str(cs)) #debug so we can see where oracle is trying to connect to/with

 # the string location of where suspended accounts should end up, change if this is different
suspended_OU = '/Suspended Accounts'
# Define a list of sub-OUs in GAdmin where users should not be moved out of. Used for special permissions, apps, licenses, etc
frozenOrgs = ['/Administrators', '/Mail Merge Users', '/Parallels Desktop Users']

# If modifying these scopes, delete the file token.json.
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



with oracledb.connect(user=un, password=pw, dsn=cs) as con: # create the connecton to the database
    with con.cursor() as cur:  # start an entry cursor
        with open('StaffLog.txt', 'w') as log:
            # Start by getting a list of schools from the schools table view to get the school names, numbers, etc for use
            cur.execute('SELECT name, school_number FROM schools')
            schools = cur.fetchall()
            for school in schools:
                # store results in variables mostly just for readability
                schoolName = school[0].title() # convert to title case since some are all caps
                schoolNum = school[1]
                # construct the string for the organization unit in Google Admin from the building name + staff
                orgUnit = '/D118 Staff/' + schoolName + ' Staff'
                print(f'{schoolName} | {schoolNum} | {orgUnit}') # debug

                # get the overall user info (non-school specific) for all users in the current school, filtering to only those who have an email filled in to avoid "fake" accounts like test/temp staff
                cur.execute('SELECT dcid, email_addr, first_name, last_name, teachernumber, groupvalue, canchangeschool FROM users WHERE email_addr IS NOT NULL AND homeschoolid = ' + str(schoolNum) + ' ORDER BY dcid DESC')
                users = cur.fetchall()
                for user in users:
                    try: # put each user in their own try block so we can skip them if they have an error
                        enabled = False # set their enabled flag to be false by default, will be set to true later if they have an active school
                        schoolAccess = [] # create empty list for which schools they have access to
                        # store the info in variables for better readability so its obvious what we pass later on
                        uDCID = str(user[0]) # get the unique DCID for that user
                        email = str(user[1])
                        firstName = str(user[2])
                        lastName = str(user[3])
                        teacherNum = str(user[4])
                        securityGroup = str(user[5])
                        if user[6]: # if they have a CLOB returned for thir can change schools field, we want to conver that to a list
                            schoolList = str(user[6].read()) # read the CLOB that is returned
                            schoolAccess = schoolList.split(';') # split up the result by semicolon into our schoolAccess list to get the individual 
                        print(str(user) + str(schoolAccess)) # debug

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
                            for schoolEntry in schoolStaff:
                                staffType = '' # reset the staff type for each user in case there is a situation where their home school is disabled?
                                schoolCode = schoolEntry[0]
                                # print(schoolEntry) # debug
                                if str(schoolCode) not in schoolAccess: # if the current school code is not in their access list, add it
                                    schoolAccess.append(str(schoolCode))
                                if schoolCode == schoolNum: # if the current school entry is their homeschool
                                    staffType = str(schoolEntry[2]) # set the staff type. 0 = Not Assigned, 1 = Teacher, 2 = Staff, 3 = Lunch Staff, 4 = Substitute
                            print(str(user) + str(schoolAccess)) # debug
                        
                        # This else block handles staff who should be inactive/suspended
                        else:
                            print(f'User {email} has no active schools, will be suspended')
                            queryString = 'Synchronization_Data.DCID=' + uDCID # construct the query string which looks for the custom Synchronization_Data custom attribute category and the DCID attribute in that category
                            queryResults = service.users().list(customer='my_customer', domain='d118.org', maxResults=2, orderBy='email', projection='full', query=queryString).execute() # return a list of at most 2 users who have that DCID
                            # print(queryResults) # debug
                            if queryResults.get('users'): # if we found a user in Google that matches the user DCID, we can suspend their account and move them to the suspended OU 
                                userToUpdateEmail = queryResults.get('users')[0].get('primaryEmail') # get the primary email from the google account results just in case its different than what is in PS
                                # print(userToUpdateEmail) # debug
                                userToUpdate = service.users().get(userKey=userToUpdateEmail).execute() # return the google account for that email
                                # print(userToUpdate) # debug
                                if userToUpdate.get('suspended') == True: # if they are already suspended we don't need to suspend them again
                                    print(f'User with email {email} and DCID {uDCID} is already suspended')
                                else:
                                    print(f'Suspending {email} with DCID {uDCID}')
                                    print(f'Suspending {email} with DCID {uDCID}', file=log)
                                    # outcome = service.users().update(userKey=userToUpdateEmail, suspended=True).execute() # the actual suspension of the account by calling an account update with susepnded set to True
                            else:
                                print(f'Warning: Found inactive user DCID {uDCID} without email conatining that Synchronization_Data. Should be {email}')
                                print(f'Warning: Found inactive user DCID {uDCID} without email conatining that Synchronization_Data. Should be {email}', file=log)
                        
                    except Exception as er:
                        print(f'Error on {user[1]}: {er}')
                        print(f'Error on {user[1]}: {er}', file=log)

