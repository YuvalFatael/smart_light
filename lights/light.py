import threading
import time
import logging
import datetime
import pyimgur
import argparse
import motion_detector
import string
import random
from configparser import ConfigParser
from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient
from AWSIoTPythonSDK.exception.AWSIoTExceptions import publishTimeoutException

# Global Vars
logger = None
myMQTTClient = None
control_condition_var = threading.Condition()
control_timestamp = None
device_id = None
device_location = None
control_timer = None
cleanup_margin = None  # number of control_timer times
# network_neighbors = {'Left': '', 'Right': ''}
network_devices = {}  # 'id': {'id': device_id, 'location': device_location, 'time': device_update_time}
network_motions = {}  # 'motion_id': {'id': motion_id, 'direction': 'motion_direction', 'deadline': motion_deadline_time}
send_control_lock = threading.Lock()
config_filename = 'config.ini'
imgur_client = None
config_parser = None


def id_generator(size=6, chars=string.ascii_lowercase + string.digits):
	return ''.join(random.choice(chars) for _ in range(size))


def control_message_handler(client, userdata, message):
	global control_timestamp
	control_msg = message.payload.decode("utf-8").split(',')  # Control message structure: 'deviceID,deviceLocation'
	message_device_id = control_msg[0]
	message_device_location = control_msg[1]

	# Got a control message I sent
	if message_device_id == device_id:
		return

	logger.debug('%s received control from %s', device_id, message_device_id)

	# Check if we need to send a control message or we just sent one
	if control_timestamp is None or message_device_id not in network_devices or time.time() - control_timestamp > 10:  # can't resend messages faster
		logger.debug('%s sending control to new device %s', device_id, message_device_id)
		threading.Thread(target=send_control).start()

	old_message_device_info = network_devices.get(message_device_id)
	# Update network devices
	update_time = time.time()
	message_device_info = {'id': message_device_id,
						   'location': message_device_location,
						   'time': update_time}
	network_devices[message_device_id] = message_device_info
	# Check if network devices should be updated
	'''if old_message_device_info is None or old_message_device_info['location'] != message_device_location:
		# Update Neighbors
		update_neighbors()'''


def motion_message_handler(client, userdata, message):
	motion_msg = message.payload.decode("utf-8").split(
		',')  # Motion message structure: 'deviceID,motionID,motion_direction,motion_speed'
	message_device_id = motion_msg[0]

	# Got a motion message I sent
	if message_device_id == device_id:
		return

	motion_id = motion_msg[1]
	motion_direction = motion_msg[2]
	motion_speed = motion_msg[3]
	sender_location = int(network_devices[message_device_id]['location'])
	my_location = get_location()
	# If the motion is coming to us
	if (motion_direction == 'Right' and my_location - sender_location > 0) or (
					motion_direction == 'Left' and my_location - sender_location < 0):
		motion_deadline = get_motion_deadline(message_device_id, motion_speed)
		motion_info = {'id': motion_id,
					   'direction': motion_direction,
					   'deadline': motion_deadline}
		network_motions[motion_id] = motion_info
		logger.debug('%s added motion %s direction: %s deadline: %s', device_id, motion_id, motion_direction,
					 datetime.datetime.fromtimestamp(motion_deadline).strftime('%d/%m/%Y %H:%M:%S'))


def alert_message_handler(client, userdata, message):
	alert_msg = message.payload.decode("utf-8").split(
		',')  # Alert message structure: 'deviceID,motionID'
	message_device_id = alert_msg[0]

	# Got a motion message I sent
	if message_device_id == device_id:
		return

	alert_motion_id = alert_msg[1]
	if alert_motion_id in network_motions:
		del network_motions[alert_motion_id]
		logger.debug('%s removed motion %s which failed to reach %s', device_id, alert_motion_id, message_device_id)


def motion_detected(direction, speed, image_filename):
	global myMQTTClient
	if myMQTTClient is None:  # For debugging
		print('direction: {}, image_filename: {}'.format(direction, image_filename))
	else:
		# We are expecting a motion
		if len(network_motions) > 0:
			motion = None
			for motion_event in network_motions.values():
				if motion is None or motion['time'] > motion_event['time']:
					motion = motion_event
			motion_id = motion['id']
		# New motion
		else:
			motion_id = id_generator()

		# Send motion event
		# neighbor_id = network_neighbors[direction]
		send_motion(motion_id, direction, speed)


'''
def update_neighbors():
	right_neighbor = None
	left_neighbor = None
	right_neighbor_distance = 0
	left_neighbor_distance = 0
	for device in network_devices.values():
		network_device_id = device['id']
		network_device_location = device['location']
		distance = float(get_location()) - float(network_device_location)
		if distance < 0 and right_neighbor_distance == 0:
			right_neighbor_distance = distance
			right_neighbor = (network_device_id, distance)
		elif distance > 0 and left_neighbor_distance == 0:
			left_neighbor_distance = distance
			left_neighbor = (network_device_id, distance)
		elif 0 > distance > right_neighbor_distance:
			right_neighbor_distance = distance
			right_neighbor = (network_device_id, distance)
		elif 0 < distance < left_neighbor_distance:
			left_neighbor_distance = distance
			left_neighbor = (network_device_id, distance)

	network_neighbors['Right'] = right_neighbor
	logger.debug('%s set right_neighbor %s', device_id, right_neighbor)

	network_neighbors['Left'] = left_neighbor
	logger.debug('%s set left_neighbor %s', device_id, left_neighbor)
'''


def cleanup_network_devices():
	# flag = 0
	for iter_device_id in list(network_devices):
		network_device_update_time = network_devices[iter_device_id]['time']
		if time.time() - network_device_update_time > control_timer * cleanup_margin:
			del network_devices[iter_device_id]
			logger.debug('%s removed offline device %s', device_id, iter_device_id)
		#		flag = 1

		# if flag == 1:
		#	update_neighbors()


def cleanup_network_thread_func():
	while True:
		time.sleep(control_timer / 2)
		cleanup_network_devices()


def send_control_thread_func():
	global control_timestamp
	while True:
		time.sleep(1)
		if time.time() - control_timestamp >= control_timer:
			logger.debug('%s sending control from send_control_thread', device_id)
			threading.Thread(target=send_control).start()


def check_motion_thread_func():
	while True:
		time.sleep(1)
		for iter_motion_id in list(network_motions):
			motion = network_motions[iter_motion_id]
			if motion['deadline'] < time.time():
				send_alert(motion['id'])
				del network_motions[motion['id']]


def send_control():
	global control_timestamp
	send_control_lock.acquire()
	control_timestamp = time.time()
	try:
		myMQTTClient.publish("control", "{},{}".format(device_id, get_location()), 1)
	except publishTimeoutException:
		logger.error('%s got TIMEOUT', device_id)
	send_control_lock.release()
	logger.debug('%s sent control with location: %s', device_id, device_location)


def send_motion(motion_id, motion_direction, motion_speed):
	try:
		myMQTTClient.publish("motion", "{},{},{},{}".format(device_id, motion_id, motion_direction, motion_speed), 1)
	except publishTimeoutException:
		logger.error('%s got TIMEOUT', device_id)
	logger.debug('%s sent motion id: %s direction: %s speed: %s', device_id, motion_id, motion_direction, motion_speed)


def send_alert(motion_id):
	try:
		myMQTTClient.publish("alert", "{},{}".format(device_id, motion_id), 1)
	except publishTimeoutException:
		logger.error('%s got TIMEOUT', device_id)
	logger.debug('%s sent alert on motion_id: %s', device_id, motion_id)


def get_location():  # TODO: implement location function
	return device_location


def mqtt_connect():
	global myMQTTClient
	# For certificate based connection
	myMQTTClient = AWSIoTMQTTClient(device_id)
	# For TLS mutual authentication
	endpoint_url = config_parser.get('mqtt', 'endpoint_url')
	endpoint_port = int(config_parser.get('mqtt', 'endpoint_port'))
	myMQTTClient.configureEndpoint(endpoint_url, endpoint_port)
	myMQTTClient.configureCredentials("certs/root-CA.crt", "certs/{}.private.key".format(device_id),
									  "certs/{}.cert.pem".format(device_id))

	myMQTTClient.configureOfflinePublishQueueing(-1)  # Infinite offline Publish queueing
	myMQTTClient.configureDrainingFrequency(2)  # Draining: 2 Hz
	myMQTTClient.configureConnectDisconnectTimeout(10)  # 10 sec
	myMQTTClient.configureMQTTOperationTimeout(5)  # 5 sec

	myMQTTClient.connect()  # Todo: try catch?
	myMQTTClient.subscribe("control", 1, control_message_handler)
	myMQTTClient.subscribe("motion", 1, motion_message_handler)
	myMQTTClient.subscribe("alert", 1, alert_message_handler)


def imgur_connect():
	global imgur_client
	imgur_client_id = config_parser.get('imgur', 'imgur_client_id')
	imgur_client = pyimgur.Imgur(imgur_client_id)


def get_motion_deadline(sender_device_id, motion_speed):
	return time.time() + abs(10 * (int(network_devices[sender_device_id]['location']) - int(get_location())))


def generate_motion_for_debug(video_filename_path):
	motion_detector.md(video_filename_path)


def get_config():
	global config_parser, device_id, device_location, control_timer, cleanup_margin
	config_parser = ConfigParser()
	config_parser.read(config_filename)
	device_id = config_parser.get('light', 'device_id')
	device_location = config_parser.getint('light', 'device_location')
	control_timer = config_parser.getint('light', 'control_timer')
	cleanup_margin = config_parser.getint('light', 'cleanup_margin')


def get_logger():
	global logger
	logger = logging.getLogger('smart_light')
	handler = logging.StreamHandler()
	formatter = logging.Formatter(
		'%(asctime)s %(name)-12s %(levelname)-8s %(message)s')
	handler.setFormatter(formatter)
	logger.addHandler(handler)
	logger.setLevel(logging.DEBUG)


def get_argparser_video():
	ap = argparse.ArgumentParser()
	ap.add_argument("-v", "--video", help="path to the video file", nargs=1)
	args = ap.parse_args()
	return args.video[0]


def main(path_to_video=None):
	# Get Config and General Parameters
	get_config()

	# Get Logger
	get_logger()

	# Connect to Amazon's MQTT service
	mqtt_connect()
	logger.debug('%s connected', device_id)

	# Connect to Imgur
	imgur_connect()
	# uploaded_image = imgur_client.upload_image('path_to_image', title="Uploaded with PyImgur")

	# Send Control Message
	send_control()

	# Create Cleanup Network thread
	cleanup_network_devices_thread = threading.Thread(target=cleanup_network_thread_func)
	cleanup_network_devices_thread.start()

	# Create Control Message thread
	control_message_thread = threading.Thread(target=send_control_thread_func)
	control_message_thread.start()

	# Create Check Motion thread
	motion_check_thread = threading.Thread(target=check_motion_thread_func)
	motion_check_thread.start()

	# Create Image processing thread for Debug
	if config_parser.getboolean('motion', 'run_video') is True:
		threading.Thread(target=motion_detector.md, args=[video, motion_detected]).start()
	# image_processing_thread = threading.Thread(target=motion_detector.md('in.avi'))
	# image_processing_thread.start()

	while True:
		pass


if __name__ == '__main__':
	video = get_argparser_video()
	main(video)
