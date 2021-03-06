import os, platform
import dynamixel
import time
import options
import math
import serial

ticks_per_rad = 4096.0/(math.pi*2)

############################################
#  _______         __ ______                     __
# /_  __(_)_ _    / // / __ \_    _____ ________/ /
#  / / / /  ' \  / _  / /_/ / |/|/ / _ `/ __/ _  / 
# /_/ /_/_/_/_/ /_//_/\____/|__,__/\_,_/_/  \_,_/  
############################################

myActuators = list()


def forwardKinematics(theta1, theta2, l1, l2):
    return [l1*math.cos(theta1)+l2*(math.cos(theta1+theta2)),
            l1*math.sin(theta1)+l2*(math.sin(theta1+theta2))]
#Given: xE,yE, l1, l2
#Return: theta1,theta2
def inverseKinematics(xIn, yIn, l1, l2):
	myTheta2 = 2*math.atan2(math.sqrt(((l1+l2)**2-(xIn**2+yIn**2))),math.sqrt((xIn**2+yIn**2.0)-(l1-l2)**2))
	myTheta1 = math.atan2(yIn,xIn)-math.atan2(l2*math.sin(myTheta2),l1+l2*math.cos(myTheta2))
	return (scaleToCircle(myTheta1), scaleToCircle(myTheta2))

def computeAltIK(x, y, theta1, theta2):
	#theta1 and 2 are IK outputs
	t2 = -theta2
	angle_to_endpoint = scaleToCircle(math.atan2(y,x))
	if angle_to_endpoint > theta1:
		t1 = theta1 + 2*(angle_to_endpoint-theta1)
	elif angle_to_endpoint < theta1:
		t1 = theta1 + 2*(angle_to_endpoint-theta1)
	else:
		t1 = theta1

	return (t1, t2)

def scaleToCircle(radianvalue):
	return radianvalue % (2*math.pi)


def boundWithinGoal(value, upper, lower):
	if value > upper:
		bounded = upper
	elif value < lower:
		bounded = lower
	else:
		bounded = value
	return bounded

def boundWithinRobotReach(x, y, radius):
	if math.sqrt(math.pow(x,2)+math.pow(y,2)) > radius:
		angle = math.atan2(y,x)
		return (radius*math.cos(angle), radius*math.sin(angle))
	else:
		return (x,y)
def withinThreshold(difference, thresh):
	if abs(difference) <= thresh:
		return True
	elif abs(abs(difference)-2*math.pi) <= thresh:
		return True
	else:
		return False

def actuatorsMoving(actuators):
    for actuator in actuators:
        if actuator.cache[dynamixel.defs.REGISTER['Moving']]:
            return True
    return False

if platform.dist()[0] == 'Ubuntu':
    portName = options.ubuntu_port
elif os.name == "posix":
    portName = options.unix_port
else:
    portName = options.windows_port

serial = dynamixel.serial_stream.SerialStream( port=portName, baudrate=options.baudrate, timeout=1)
net = dynamixel.dynamixel_network.DynamixelNetwork( serial )
net.scan( 1, options.num_servos )

print "Scanning for Dynamixels...",
for dyn in net.get_dynamixels():
    print dyn.id,
    myActuators.append(net[dyn.id])

print "FOUND:" + str(myActuators)

for actuator in myActuators:
	actuator.moving_speed = options.servo_speed
	actuator.synchronized = True
	actuator.torque_enable = True
	actuator.torque_control_enable = False
	actuator.torque_limit = 1024
	actuator.max_torque = 1024


class Arm(object):

	def __init__(self, shoulder, elbow, params):
		self.params = params
		self.shoulder = shoulder
		self.elbow = elbow
		self.elbow_angle = 0
		self.shoulder_angle = 0
		#motors

	def update(self):
		net.synchronize()
		self.shoulder.read_all()
		self.elbow.read_all()

	def moveToXY(self,x,y):
		theta1, theta2 = inverseKinematics(x,y, self.params.l1, self.params.l2)
		(shoulderCurr, elbowCurr) = self.returnCurrentPositions()
		(shoulderCurrNOMOD, elbowCurrNOMOD) = self.returnCurrentPositionsNOMOD()

		alpha = shoulderCurr - theta1
		if abs(alpha) > abs(shoulderCurr - (theta1+2*math.pi)):
			alpha = shoulderCurr - (theta1+2*math.pi)
		if abs(alpha) > abs(shoulderCurr - (theta1-2*math.pi)):
			alpha = shoulderCurr - (theta1-2*math.pi)

		beta = elbowCurr - theta2
		if abs(beta) > abs(elbowCurr - (theta2+2*math.pi)):
			beta = elbowCurr - (theta2+2*math.pi)
		if abs(beta) > abs(elbowCurr - (theta2-2*math.pi)):
			beta = elbowCurr - (theta2-2*math.pi)

		self.moveToTheta(shoulderCurrNOMOD-alpha, elbowCurrNOMOD-beta)


	def moveToXYGoal(self, x, y):
		x, y = Arm.transformGoaltoRobot(self,x,y)
		x, y = boundWithinRobotReach(x,y, self.params.l1+self.params.l2)
		x = boundWithinGoal(x, self.params.max_x, self.params.min_x)
		y = boundWithinGoal(y, self.params.max_y, self.params.min_y)
		self.moveToXY(x,y)


	def transformGoaltoRobot(self,x,y):
		return (x-self.params.horizontal_offset, y-self.params.vertical_offset)


	def moveToTheta(self, t1, t2):
		#print t1, t2
		self.shoulder_angle = t1
		self.elbow_angle = t2
		self.shoulder.goal_position = int((self.shoulder_angle*ticks_per_rad)+self.params.shoulder_offset)
		self.elbow.goal_position = int(((self.elbow_angle*ticks_per_rad) +self.params.elbow_offset)/2)


	def isMoving(self):
	    for actuator in [self.shoulder, self.elbow]:
	        if actuator.cache[dynamixel.defs.REGISTER['Moving']]:
	            return True
	    return False


	def returnCurrentPositions(self):
		theta1 = (self.shoulder.cache[dynamixel.defs.REGISTER['CurrentPosition']]-self.params.shoulder_offset)/ticks_per_rad
		theta2 = (self.elbow.cache[dynamixel.defs.REGISTER['CurrentPosition']]-self.params.elbow_offset)/ticks_per_rad*2
		theta1 = scaleToCircle(theta1)
		theta2 = scaleToCircle(theta2)
		return (theta1, theta2)

	def returnCurrentPositionsNOMOD(self):
		theta1 = (self.shoulder.cache[dynamixel.defs.REGISTER['CurrentPosition']]-self.params.shoulder_offset)/ticks_per_rad
		theta2 = (self.elbow.cache[dynamixel.defs.REGISTER['CurrentPosition']]-self.params.elbow_offset)/ticks_per_rad*2
		return (theta1, theta2)

	def nearGoalPosition(self):
		shoulder, elbow = Arm.returnCurrentPositions(self)
		if withinThreshold(scaleToCircle(shoulder-self.shoulder_angle),self.params.angle_threshold) and withinThreshold(scaleToCircle(elbow-self.elbow_angle),self.params.angle_threshold):
			return True
		else:
			return False
		



a = Arm(myActuators[0], myActuators[1], options.left_arm)

goal = (0,0)
a.update()
#a.moveToXYGoal(goal[0], goal[1])

while True:
	try:
		a.update()
		(theta1, theta2) = a.returnCurrentPositions()
		currXY = forwardKinematics(theta1, theta2, options.left_arm.l1, options.left_arm.l2) #in robot coords
		currXY_world = [currXY[0]+options.left_arm.horizontal_offset, currXY[1]+options.left_arm.vertical_offset]
		gamma = math.atan2(goal[1]-currXY_world[1], goal[0]-currXY_world[0])
		l=1.5
		#if not a.nearGoalPosition():
		a.moveToXYGoal(currXY_world[0]+l*math.cos(gamma), currXY_world[1]+l*math.sin(gamma))
		print currXY_world + [currXY_world[0]+l*math.cos(gamma), currXY_world[1]+l*math.sin(gamma)]
	except KeyboardInterrupt:
		break
