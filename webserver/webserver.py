import logging
import time
import threading
import datetime
from configparser import ConfigParser
from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient
from flask import Flask, render_template, redirect
from operator import itemgetter

# Global Vars
app = Flask(__name__)
logger = None
myMQTTClient = None
network_devices = {}  # {'id': device_id, 'location': device_location, 'time': device_update_time}
network_events = []
device_id = None
control_timer = None
cleanup_margin = None  # number of control_timer times
cleanup_network_devices_thread = None
endpoint_url = None
endpoint_port = None
config_filename = 'config.ini'


def control_message_handler(client, userdata, message):
	control_msg = message.payload.decode("utf-8").split(',')  # Control message structure: 'deviceID,deviceLocation'
	message_device_id = control_msg[0]
	message_device_location = control_msg[1]

	# Got the control message I sent
	if message_device_id == device_id:
		return

	logger.debug('%s received control from %s', device_id, message_device_id)

	# Update network devices
	update_time = time.time()
	update_time_str = datetime.datetime.fromtimestamp(update_time).strftime('%d/%m/%Y %H:%M:%S')
	message_device_info = {'id': message_device_id,
						   'location': message_device_location,
						   'time': update_time,
						   'time_str': update_time_str}
	# New device connected to network
	if message_device_id not in network_devices.keys():
		event = {'id': message_device_id,
				 'event': '{} connected to network'.format(message_device_id),
				 'time': update_time,
				 'time_str': update_time_str}
		network_events.append(event)
	network_devices[message_device_id] = message_device_info
	logger.debug('%s updated network_devices: %s', device_id, str(message_device_info))


def motion_message_handler(client, userdata, message):  # TODO: implement event message handler
	motion_msg = message.payload.decode("utf-8").split(
		',')  # Motion message structure: 'deviceID,motionID,motion_direction,motion_speed'
	message_device_id = motion_msg[0]
	motion_id = motion_msg[1]
	motion_direction = motion_msg[2]
	motion_speed = motion_msg[3]

	# Create Motion event
	update_time = time.time()
	update_time_str = datetime.datetime.fromtimestamp(update_time).strftime('%d/%m/%Y %H:%M:%S')
	event = {'id': message_device_id,
			 'event': '{} detected motion id: {}, direction: {}, speed: {}'.format(message_device_id, motion_id,
																				   motion_direction, motion_speed),
			 'time': update_time,
			 'time_str': update_time_str}
	network_events.append(event)
	logger.debug('%s added motion: %s, %s, %s', device_id, motion_id, motion_direction, motion_speed)


def alert_message_handler(client, userdata, message):  # TODO: implement event message handler
	alert_msg = message.payload.decode("utf-8").split(',')  # Alert message structure: 'deviceID,motionID'
	message_device_id = alert_msg[0]
	motion_id = alert_msg[1]

	# Create Alert event
	update_time = time.time()
	update_time_str = datetime.datetime.fromtimestamp(update_time).strftime('%d/%m/%Y %H:%M:%S')
	event = {'id': message_device_id,
			 'event': '{} motion id: {} is missing!!!'.format(message_device_id, motion_id),
			 'time': update_time,
			 'time_str': update_time_str}
	network_events.append(event)
	logger.debug('%s alert on motion: %s', device_id, motion_id)


def cleanup_neighbors():
	for iter_device_id in list(network_devices):
		network_device_update_time = network_devices[iter_device_id]['time']
		if time.time() - network_device_update_time > control_timer * cleanup_margin:
			update_time = time.time()
			update_time_str = datetime.datetime.fromtimestamp(update_time).strftime('%d/%m/%Y %H:%M:%S')
			event = {'id': network_devices[iter_device_id]['id'],
					 'event': '{} disconnected from network'.format(network_devices[iter_device_id]['id']),
					 'time': update_time,
					 'time_str': update_time_str}
			network_events.append(event)
			del network_devices[iter_device_id]
			logger.debug('%s removed offline device %s', device_id, iter_device_id)


def cleanup_network_thread_func():
	while True:
		time.sleep(control_timer / 2)
		cleanup_neighbors()


def mqtt_connect():
	global myMQTTClient
	# For certificate based connection
	myMQTTClient = AWSIoTMQTTClient(device_id)  # Todo: all these should be environment vars ?
	# For TLS mutual authentication
	myMQTTClient.configureEndpoint("audsodu4ke8z4.iot.us-west-2.amazonaws.com", 8883)
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


@app.route("/clear")
def clear():
	global network_events
	network_events = []
	return redirect("/", code=302)


@app.route("/")
def page():
	network_devices_list_sorted = sorted(network_devices.values(), key=itemgetter('location'), reverse=False)
	return render_template('page.html', events=network_events, devices=network_devices_list_sorted,
						   num_devices=len(network_devices_list_sorted) + 1)


def get_config():
	global device_id, control_timer, cleanup_margin, endpoint_url, endpoint_port
	parser = ConfigParser()
	parser.read(config_filename)
	device_id = parser.get('light', 'device_id')
	control_timer = int(parser.get('light', 'control_timer'))
	cleanup_margin = int(parser.get('light', 'cleanup_margin'))
	endpoint_url = parser.get('mqtt', 'endpoint_url')
	endpoint_port = int(parser.get('mqtt', 'endpoint_port'))


def main():
	global logger, cleanup_network_devices_thread

	# Get Config Parameters
	get_config()

	# Logging congif
	logger = logging.getLogger('smart_light')
	handler = logging.StreamHandler()
	formatter = logging.Formatter(
		'%(asctime)s %(name)-12s %(levelname)-8s %(message)s')
	handler.setFormatter(formatter)
	logger.addHandler(handler)
	logger.setLevel(logging.DEBUG)

	# Connect to Amazon's MQTT service
	mqtt_connect()
	logger.debug('%s connected', device_id)

	# Create Cleanup Network thread
	cleanup_network_devices_thread = threading.Thread(target=cleanup_network_thread_func)
	cleanup_network_devices_thread.start()

	# Run webserver
	app.run()


if __name__ == '__main__':
	main()
