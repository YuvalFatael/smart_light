import logging
import time
import threading
from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient
from flask import Flask, render_template


# Global Vars
device_id = 'webserver'
app = Flask(__name__)
logger = None
myMQTTClient = None
network_devices = {}  # {'id': device_id, 'location': device_location, 'time': device_update_time}
control_timer = 30  # Todo: should be an environment var
cleanup_margin = 2  # number of control_timer times  # Todo: should be an environment var
cleanup_network_devices_thread = None


def control_message_handler(client, userdata, message):
	global control_timestamp, control_message_thread
	control_msg = message.payload.decode("utf-8").split(',')  # Control message structure: 'deviceID,deviceLocation'
	message_device_id = control_msg[0]
	message_device_location = control_msg[1]

	# Got the control message I sent
	if message_device_id == device_id:
		return

	logger.debug('%s received control from %s', device_id, message_device_id)

	old_message_device_info = network_devices.get(message_device_id)
	# Update network devices
	message_device_info = {'id': message_device_id, 'location': message_device_location, 'time': time.time()}
	network_devices[message_device_id] = message_device_info
	logger.debug('%s updated network_devices: %s', device_id, str(message_device_info))


def event_message_handler(client, userdata, message):  # TODO: implement event message handler
	pass


def cleanup_neighbors():
	for iter_device_id in list(network_devices):
		network_device_update_time = network_devices[iter_device_id]['time']
		if time.time() - network_device_update_time > control_timer * cleanup_margin:
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
	myMQTTClient.configureCredentials("certs/root-CA.crt", "certs/{}.private.key".format(device_id), "certs/{}.cert.pem".format(device_id))

	myMQTTClient.configureOfflinePublishQueueing(-1)  # Infinite offline Publish queueing
	myMQTTClient.configureDrainingFrequency(2)  # Draining: 2 Hz
	myMQTTClient.configureConnectDisconnectTimeout(10)  # 10 sec
	myMQTTClient.configureMQTTOperationTimeout(5)  # 5 sec

	myMQTTClient.connect() 	# Todo: try catch?
	myMQTTClient.subscribe("control", 1, control_message_handler)
	myMQTTClient.subscribe("events", 1, event_message_handler)


@app.route("/")
def page():
	events_list = {'device1': 'connect', 'device2' : 'connect'}
	return render_template('page.html', events=events_list)


def main():
	global logger, cleanup_network_devices_thread

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
