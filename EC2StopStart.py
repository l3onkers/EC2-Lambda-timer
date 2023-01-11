from datetime import datetime, date
from urllib.request import urlopen
import boto3
import re

t = datetime.now()
DEBUG = True

ec2_client = boto3.client('ec2')

def match(unit, range):
    '''
    Main function to compare the current time with the time defined in cron expression
    The main purpose of this funcion is validate types and formats, and decide if 'unit' match with 'range'
    
    "Unit" must be an integer with the current time
    "Range" must be a string with the value or values defined in cron expression
    '''
    
    # Validate types
    if type(range) is not str or type(unit) is not int:
        return False
    
    # For wildcards, accept all
    if range == "*":
        return True
    
    # Range parameter must match with some valid cron expression (number, range or enumeration) -> "*", "0", "1-3", "1,3,5,7", etc
    pattern = re.compile("^[0-9]+-[0-9]+$|^[0-9]+(,[0-9]+)*$")
    if not pattern.match(range):
        #print "There is an error in the cron line"
        return False
    
    # If range's length = 1, must be the exact unit number
    if 1 <= len(range) <= 2:
        if unit == int(range):
            return True
    
    # For ranges, the unit must be among range numbers
    if "-" in range:
        units = range.split("-")
        if int(units[0]) <= unit <= int(units[1]):
            return True
        else:
            return False
    
    # For enumerations, the unit must be one of the elements in the enumeration
    if "," in range:
        if str(unit) in range:
            return True
    
    return False

def checkMinutes(cronString):
     
    t = datetime.now()
    
    return match(t.minute, cronString.split()[0] )

def checkHours(cronString):
    
    t = datetime.now()
    
    return match(t.hour, cronString.split()[1])

def checkDays(cronString):
    
    t = datetime.now()
    
    return match(t.day, cronString.split()[2])

def checkMonths(cronString):

    t = datetime.now()
    
    return match(t.month, cronString.split()[3])

def checkWeekdays(cronString):

    t = datetime.now()
    
    return match(t.isoweekday(), cronString.split()[4])
        
def isTime(cronString):
    '''
    This function returns True if this precise moment match with the cron expression.
    This functions can be as smart as you need. Right now, it only match the present hour
    with the hour defined in the cron expression.
    '''
    
    if checkMinutes(cronString) and checkHours(cronString) and checkDays(cronString) and checkMonths(cronString) and checkWeekdays(cronString):
        return True
    
def cronEC2Exec(cron, instance, action):
    '''
    Function to control operations on EC2 instances
    '''
    if DEBUG:   print("> {2}. Current date is {0} and cron expression is {1}".format(t, cron, action))
    if cron == "":
        print("Empty cron expression!")
        return True
    
    if isTime(cron):
        if action == "start" and instance.state["Name"] == "stopped":
            # Start Instance
            print("#################################")
            print("## Starting instance {0}...".format(instance.id))
            print("#################################")
            instance.start()
            
        if action == "stop" and instance.state["Name"] == "running":
            # Stop instance
            print("#################################")
            print("## Stopping instance {0}...".format(instance.id))
            print("#################################")
            instance.stop()
            
def checkEC2(ec2):
    '''
    List tags in EC2 instances and perform operations on instances
    '''
    
    for i in ec2.instances.all():
        #print "> Instance {0} is {1}".format(i.id, i.state["Name"])
        if i.tags:
            for tag in i.tags:
                if tag['Key'] == "startInstance":
                    if DEBUG:   print(">> Found an 'startInstance' tag on instance {}...".format(i.id))
                    cronEC2Exec(tag['Value'], i, "start")
            
                if tag['Key'] == "stopInstance":
                    if DEBUG:   print(">> Found an 'stopInstance' tag on instance {}...".format(i.id))
                    cronEC2Exec(tag['Value'], i, "stop")

    return True

def lambda_handler(event, context):
    
    # start connectivity
    s = boto3.Session()
    ec2 = s.resource('ec2')
    
    try:
        if checkEC2(ec2):
            print("EC2 checked!")

    except Exception as e:
        print('Check failed!')
        print(str(e))
        raise
    finally:
        print(('Check complete at {}'.format(str(datetime.now()))))
        return "OK"