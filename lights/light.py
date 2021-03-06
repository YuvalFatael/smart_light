import threading
import time
import logging
import datetime
import pyimgur
import argparse
from motion_detector import md
import string
import random
import os
from configparser import ConfigParser
from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient
from AWSIoTPythonSDK.exception.AWSIoTExceptions import publishTimeoutException

# Global Vars
logger = None
myMQTTClient = None
control_timestamp = None
device_id = None
device_location = None
control_timer = None
cleanup_factor = None  # number of control_timer times
deadline_factor = None
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

	# Update network devices
	update_time = time.time()
	message_device_info = {'id': message_device_id,
						   'location': message_device_location,
						   'time': update_time}
	network_devices[message_device_id] = message_device_info


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
		motion_deadline = get_motion_deadline(message_device_id, float(motion_speed))
		motion_info = {'id': motion_id,
					   'time': time.time(),
					   'direction': motion_direction,
					   'deadline': motion_deadline}
		network_motions[motion_id] = motion_info
		logger.debug('%s recived motion from: %s id: %s direction: %s deadline: %s', device_id, message_device_id,
					 motion_id, motion_direction,
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
				if motion_event['direction'] != direction:
					continue
				if motion is None:
					motion = motion_event
				elif motion['time'] > motion_event['time']:
					motion = motion_event
			if motion is None:
				motion_id = id_generator()
			else:
				motion_id = motion['id']
				del network_motions[motion_id]
		# New motion
		else:
			motion_id = id_generator()
		# Upload Img and Send motion event
		if config_parser.getboolean('imgur', 'upload_img'):
			threading.Thread(target=upload_image, args=[motion_id, image_filename]).start()

		# Send motion message
		send_motion(motion_id, direction, speed)


def cleanup_network_devices():
	# flag = 0
	for iter_device_id in list(network_devices):
		network_device_update_time = network_devices[iter_device_id]['time']
		if time.time() - network_device_update_time > control_timer * cleanup_factor:
			del network_devices[iter_device_id]
			logger.debug('%s removed offline device %s', device_id, iter_device_id)


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


def send_motion(motion_id, motion_direction, motion_speed, img_url=None):
	try:
		myMQTTClient.publish("motion",
							 "{},{},{},{},{}".format(device_id, motion_id, motion_direction, motion_speed, img_url), 1)
	except publishTimeoutException:
		logger.error('%s got TIMEOUT', device_id)
	logger.debug('%s sent motion id: %s direction: %s speed: %s', device_id, motion_id, motion_direction, motion_speed)


def send_alert(motion_id):
	try:
		myMQTTClient.publish("alert", "{},{}".format(device_id, motion_id), 1)
	except publishTimeoutException:
		logger.error('%s got TIMEOUT', device_id)
	logger.debug('%s sent alert on motion_id: %s', device_id, motion_id)


def send_image(motion_id, image_link):
	try:
		myMQTTClient.publish("image", "{},{},{}".format(device_id, motion_id, image_link), 1)
	except publishTimeoutException:
		logger.error('%s got TIMEOUT', device_id)
	logger.debug('%s sent image on motion_id: %s, link: %s', device_id, motion_id, image_link)


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


def upload_image(motion_id, image_filename):
	uploaded_image = imgur_client.upload_image(image_filename, title="motion")
	image_link = uploaded_image.link
	send_image(motion_id, image_link)


def get_motion_deadline(sender_device_id, motion_speed):
	distance = abs(int(network_devices[sender_device_id]['location']) - int(get_location()))
	deadline_time = distance / abs(motion_speed) * deadline_factor
	return time.time() + deadline_time


def get_config():
	global config_parser, device_id, device_location, control_timer, cleanup_factor, deadline_factor
	config_parser = ConfigParser()
	config_parser.read(config_filename)
	device_id = config_parser.get('light', 'device_id')
	device_location = config_parser.getint('light', 'device_location')
	control_timer = config_parser.getint('light', 'control_timer')
	cleanup_factor = config_parser.getfloat('light', 'cleanup_factor')
	deadline_factor = config_parser.getfloat('light', 'deadline_factor')


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
	ap.add_argument("-k", "--kill", help="kill time", nargs=1, type=float)
	args = ap.parse_args()
	video_path = None
	kill_time = None
	if args.video is not None:
		video_path = args.video[0]
	if args.kill is not None:
		kill_time = args.kill[0]
	return video_path, kill_time


def main(video_path=None, kill_time=None):
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
	if config_parser.getboolean('light', 'run_video') is True:
		threading.Thread(target=md, args=[video_path, motion_detected]).start()

	if kill_time:
		time.sleep(kill_time)
		os._exit(1)


if __name__ == '__main__':
	video, kill = get_argparser_video()
	main(video, kill)
