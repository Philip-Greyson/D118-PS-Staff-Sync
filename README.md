# # D118-PS-Staff-Sync

Scripts to synchronize staff data from PowerSchool to Google profiles.

## Overview

This script looks at staff members in PowerSchool, finds a matching Google profile for them and updates their information and Organizational Unit, suspends them if they are inactive, or creates them if they do not already exist.
It connects to the PowerSchool database and queries all buildings getting the name and schoolid, and uses the name to construct the proper Organizational Unit for the users to be in. Each school is then iterated through, and users with an email filled in the information page are queried for each building. The user's DCID (unique internal PowerSchool ID) is used to query Google profiles using a custom attribute which holds that value, and if a matching one is found, the information in PowerSchool is compared against the information currently in the profile. Any differences will be updated in the Google profile, including moving it to the correct building Organization Unit or suspending/re-enabling the account if they are inactive or are newly active. If no matching DCID in the custom attribute is found, it attempts to create a new user with the PowerSchool information. It will not be able to create the account if the email is already in use, so if a new user is made in PowerSchool but it has the same email as an existing user it will not overwrite it.
As it searches for a DCID stored in a custom attribute in the Google profile, this custom attribute will already need to be created through Google Admin (see requirements below), and it will need to be populated with the correct DCID numbers for each staff member (either manually for a small number of users or by using a quick export from PowerSchool to get the email and DCID and have a simpler script update that field based on the spreadsheet after manual review to ensure there are no duplicate entries).

## Requirements

The following Environment Variables must be set on the machine running the script:

- POWERSCHOOL_READ_USER
- POWERSCHOOL_DB_PASSWORD
- POWERSCHOOL_PROD_DB

These are fairly self explanatory, and just relate to the usernames, passwords, and host IP/URLs for PowerSchool. If you wish to directly edit the script and include these credentials or to use other environment variable names, you can.

Additionally, the following Python libraries must be installed on the host machine (links to the installation guide):

- [Python-oracledb](https://python-oracledb.readthedocs.io/en/latest/user_guide/installation.html)
- [Python-Google-API](https://github.com/googleapis/google-api-python-client#installation)

In addition, an OAuth credentials.json file must be in the same directory as the overall script. This is the credentials file you can download from the Google Cloud Developer Console under APIs & Services > Credentials > OAuth 2.0 Client IDs. Download the file and rename it to credentials.json. When the program runs for the first time, it will open a web browser and prompt you to sign into a Google account that has the permissions to disable, enable, deprovision, and move the devices. Based on this login it will generate a token.json file that is used for authorization. When the token expires it should auto-renew unless you end the authorization on the account or delete the credentials from the Google Cloud Developer Console. One credentials.json file can be shared across multiple similar scripts if desired.
There are full tutorials on getting these credentials from scratch available online. But as a quickstart, you will need to create a new project in the Google Cloud Developer Console, and follow [these](https://developers.google.com/workspace/guides/create-credentials#desktop-app) instructions to get the OAuth credentials, and then enable APIs in the project (the Admin SDK API is used in this project).

Finally, in Google Admin, you must create custom at least one custom attribute category and field for the synchronization to work, as the script compares the PowerSchool DCID to this custom field (and it should be populated for staff members before starting to run this script). This can be done from Directory > Users > More Options > Manage Custom Attributes. You can create a new category or use an existing one if you have other custom attributes, but you should make a new attribute that will contain the DCID. There is also the option to have other custom attributes, which will include the homeschool, school access list, staff type, staff group in the main custom attribute category. In addition to those, we have a separate category which also houses the building name and their cell phone number which we use for CrisisGO.

If there are spaces, or you made an attribute but deleted it and then made a new one with the same name, the names can sometimes not match what they are actually called internally in Google. To see all the custom attributes for a user, you can use `print(user.get('customSchemas', {}))` inside a user query that includes `projection = full` and it will show all their custom attribute category and field names, which you can then use to plug into the constants.

Take the names of the category and field name and set the `CUSTOM_ATTRIBUTE_SYNC_CATEGORY` and `CUSTOM_ATTRIBUTE_DCID` constants in the main script to match them. If you want to use all the additional attributes, change the constants to match your custom attribute names. **If you don't want to use the extra attributes, make sure you change `USE_EXTRA_CUSTOM_ATTRIBUTES` to False.**  

You must also have a field in PowerSchool that the staff cell phone number is stored in, we have a custom table and field named u_humanresources.cellphone, but it should be changed to wherever you store that (if anywhere) in the main SQL query, or removed if you are not going to use the extra custom attributes.

## Customization

This script is an extremely customized for our specific use case at D118. I have done my best to break out specific organizational units (OUs) and things to constants which you can change at the top of the main script, see below for what you will want to change and why.

**However, there are some assumptions the script makes due to how our organizational units (OUs) are organized.** If you do not have a similar structure you will likely need to overhaul large parts of the script to get them to work. We have an overall staff OU, then within that each building has an OU constructed from the name of the building plus a suffix. The exception to this is for suspended accounts and substitute teachers, which are placed in their own top-level OUs.

- As discussed in the requirements section, `CUSTOM_ATTRIBUTE_SYNC_CATEGORY`, `CUSTOM_ATTRIBUTE_DCID` should match the names of the custom attributes in Google Admin.
  - To use the additional custom attributes, make sure `USE_EXTRA_CUSTOM_ATTRIBUTES` is set to True, and change `CUSTOM_ATTRIBUTE_SCHOOL`, `CUSTOM_ATTRIBUTE_ACCESS_LIST`, `CUSTOM_ATTRIBUTE_TYPE`, `CUSTOM_ATTRIBUTE_GROUP`, and `CUSTOM_ATTRIBUTE_ID` to the attribute field names that are in the same category as the sync category. Additionally, there can be a separate category for CrisisGO which we store their cell phone number and building name in, so set `CUSTOM_ATTRIBUTE_CRISISGO_CATEGORY`, `CUSTOM_ATTRIBUTE_CELL`, `CUSTOM_ATTRIBUTE_BUILDING` to the relevant category and field names (the category could be the same as the sync category if you want).
  - If you are going to use the extra attributes, you will also want to change the ugly statement that begins with `if homeschool == '0' or homeschool == 131...` that we use to overwrite building names for CrisisGO and either change the `building = ''` overwrite, or delete the homeschool IDs to ones you dont use.
- `GOOGLE_DOMAIN` should be pretty self explanatory, it is the domain in which the Google profiles reside in. This is used for the account searches.
- `OU_PREFIX` is the overall umbrella organization unit name for staff. It is used as the prefix before the school specific OUs.
  - Similarly, `BUILDING_OU_SUFFIX` is the string that is appended after the building name on the suffix of the OU.
  - If you need to construct the building OUs differently, you will need to edit the `buildingOrgUnit = OU_PREFIX + schoolName + BUILDING_OU_SUFFIX` line to fit your needs.
- Suspended/inactive accounts are placed directly in the `SUSPENDED_OU` so it should be changed to the relevant OU for storing those accounts.
- Substitute teacher accounts are also placed directly in the `SUBSTITUTE_OU` which should be changed for your needs. The script checks whether their building name in PowerSchool matches the `SUB_BUILDING_NAME` to determine this, so you will need to change that to match the PowerSchool building name that your substitutes are in (or change how it determines substitutes if you do not have a separate building in PowerSchool).
- `FROZEN_OUS` is the list of suffixes that an OU will have when you do not want students to be moved out of it by this script. For example, building administration has special policies and app access, so by including `"/Administrators"` any OUs that are named that in their respective buildings will be ignored by the moving part of this script.
- `NEW_PASSWORD` is the password that is assigned to new staff accounts that are created through this script. You should change it to be relevant to your district, we have a generic one that is then overwritten during onboarding.
- This script also will remove newly suspended accounts from any Google Groups (email lists) that they belong to when they get suspended. If you want to disable this, change `REMOVE_SUSPENDED_FROM_GROUPS` to be False.
- The script will skip over users whose emails are purely numeric (eg <12345@test.com>) by default, this can be disabled by changing `SKIP_NUMERIC_EMAILS` to False.
- Finally, if you have test accounts you don't want to be processed by the script (or need to skip over specific students for some reason), you can use the `BAD_NAMES` list to skip anyone who matches their lowercase first or last name to a name in the list.
