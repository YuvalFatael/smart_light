import threading
import time
import logging
from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient
from AWSIoTPythonSDK.exception.AWSIoTExceptions import publishTimeoutException

# Global Vars
logger = None
myMQTTClient = None
control_condition_var = threading.Condition()
control_timestamp = None
device_id = "light1"  # Todo: should be an environment var
device_location = 1  # Todo: should be an environment var
control_timer = 30  # Todo: should be an environment var
cleanup_margin = 2  # number of control_timer times  # Todo: should be an environment var
cleanup_network_devices_thread = None
control_message_thread = None
network_neighbors = {'Left': None, 'Right': None}
network_devices = {}  # Todo: replace tuples (device_id, device_location, device_update_time) with dictionaries
send_control_lock = threading.Lock()


def control_message_heandler(client, userdata, message):
	global control_timestamp, control_message_thread
	control_msg = message.payload.decode("utf-8").split(',')  # Control message structure: 'deviceID,deviceLocation'
	message_device_id = control_msg[0]
	message_device_location = control_msg[1]

	# Got the control message I sent
	if message_device_id == device_id:
		return

	logger.debug('%s received control from %s', device_id, message_device_id)

	# Check if we need to send a control message or we just sent one
	if control_timestamp is None or message_device_id not in network_devices or time.time() - control_timestamp > 10:  # can't resend messages faster
		logger.debug('%s sending control to new device %s', device_id, message_device_id)
		send_control()

	old_message_device_info = network_devices.get(message_device_id)
	# Update network devices
	message_device_info = (message_device_id, message_device_location, time.time())
	network_devices[message_device_id] = message_device_info
	# Check if network devices should be updated
	if old_message_device_info is None or old_message_device_info[1] != message_device_location:
		# Update Neighbors
		update_neighbors()


def event_message_handler(client, userdata, message):  # TODO: implement event message handler
	pass


def update_neighbors():
	right_neighbor = None
	left_neighbor = None
	right_neighbor_distance = 0
	left_neighbor_distance = 0
	for network_device_id, network_device_location, _ in network_devices.values():
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


def cleanup_neighbors():
	flag = 0
	for iter_device_id in list(network_devices):
		_, _, network_device_update_time = network_devices[iter_device_id]
		if time.time() - network_device_update_time > control_timer + 10:
			del network_devices[iter_device_id]
			logger.debug('%s removed offline device %s', device_id, iter_device_id)
			flag = 1

	if flag == 1:
		update_neighbors()


def cleanup_network_thread_func():
	time.sleep(control_timer * cleanup_margin)
	cleanup_neighbors()


def send_control_thread_func():
	while True:
		time.sleep(1)
		if time.time() - control_timestamp >= control_timer:
			logger.debug('%s sending control from send_control_thread', device_id)
			send_control()


def send_control():
	global control_timestamp
	send_control_lock.acquire()
	control_timestamp = time.time()
	try:
		myMQTTClient.publish("control", "{},{}".format(device_id, get_location()), 1)
	except publishTimeoutException:
		logger.error('%s got TIMEOUT', device_id)
	send_control_lock.release()
	logger.debug('%s sent control with locaiton: %s', device_id, device_location)


def get_location():  # TODO: implement location function
	return device_location


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
	myMQTTClient.subscribe("control", 1, control_message_heandler)
	myMQTTClient.subscribe("events", 1, event_message_handler)
	# myMQTTClient.unsubscribe("test")
	#myMQTTClient.disconnect()


def main():
	global cleanup_network_devices_thread, control_message_thread, logger

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

	# Send Control Message
	send_control()

	# Create Cleanup Network thread
	cleanup_network_devices_thread = threading.Thread(target=cleanup_network_thread_func)
	cleanup_network_devices_thread.start()

	# Create Control Message thread
	control_message_thread = threading.Thread(target=send_control_thread_func)
	control_message_thread.start()

	while True:
		pass

if __name__ == '__main__':
	main()
