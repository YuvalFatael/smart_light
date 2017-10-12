import threading
import time
from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient

# Global Vars
myMQTTClient = None
control_condition_var = threading.Condition()
control_timestamp = None
device_id = "thing1"  # Todo: should be an environment var
control_timer = 10  # Todo: should be an environment var
cleanup_margin = 5  # Todo: should be an environment var
cleanup_network_devices_thread = None
control_message_thread = None
network_neighbors = {'Left': None, 'Right': None}
network_devices = []


def control_message_heandler(client, userdata, message):
	global control_timestamp
	# Check if we need to send a control message or we just sent one
	if control_timestamp is None or time.time()-control_timestamp > 10:
		send_control()
		if control_message_thread is not None:
			control_message_thread.stop()
			control_message_thread.start()

	# Update network devices
	control_msg = message.payload.strip(',')  # Control message structure: 'deviceID,deviceLocation'
	network_devices.append(control_msg[0], control_msg[1], time.time())

	# Update Neighbors
	update_neighbors()


def event_message_handler(client, userdata, message): # TODO: implement event message handler
	pass


def update_neighbors():
	right_neighbor = None
	left_neighbor = None
	right_neighbor_distance = 0
	left_neighbor_distance = 0
	for network_device_id, network_device_location, _ in network_devices:
		distance = float(get_location()) - network_device_location
		if distance > 0 and right_neighbor_distance == 0:
			right_neighbor_distance = distance
			right_neighbor = (network_device_id, distance)
		elif distance < 0 and left_neighbor_distance == 0:
			left_neighbor_distance = distance
			left_neighbor = (network_device_id, distance)
		elif 0 < distance < right_neighbor_distance:
			right_neighbor_distance = distance
			right_neighbor = (network_device_id, distance)
		elif 0 > distance > left_neighbor_distance:
			left_neighbor_distance = distance
			left_neighbor = (network_device_id, distance)

	if right_neighbor is not None:
		network_neighbors['Right'] = right_neighbor

	if left_neighbor is not None:
		network_neighbors['Left'] = left_neighbor


def cleanup_neighbors():
	flag = 0
	for device in network_devices:
		_, _, network_device_update_time = device
		if time.time() - network_device_update_time > control_timer + 5:
			network_devices.remove(device)
			flag = 1

	if flag == 1:
		update_neighbors()


def cleanup_network_thread_func():
	while True:
		time.sleep(control_timer + cleanup_margin)
		cleanup_neighbors()


def send_control_thread_func():
	while True:
		time.sleep(control_timer)
		send_control()


def send_control():
	global control_timestamp
	myMQTTClient.publish("control", "{},{}".format(device_id, get_location()), 0)
	control_timestamp = time.time()


def get_location():  # TODO: implement location function
	return '1'


def mqtt_connect():
	global myMQTTClient
	# For certificate based connection
	myMQTTClient = AWSIoTMQTTClient("light")  # Todo: all these should be environment vars ?
	# For TLS mutual authentication
	myMQTTClient.configureEndpoint("audsodu4ke8z4.iot.us-west-2.amazonaws.com", 8883)
	myMQTTClient.configureCredentials("certs/root-CA.crt", "certs/private.key", "certs/cert.pem")

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
	global cleanup_network_devices_thread, control_message_thread

	# Connect to Amazon's MQTT service
	mqtt_connect()

	# Send Control Message
	send_control()

	# Create Cleanup Network thread
	cleanup_network_devices_thread = threading.Thread(target=cleanup_network_thread_func)
	cleanup_network_devices_thread.start()

	# Create Control Message thread
	control_message_thread = threading.Thread(target=send_control_thread_func)
	cleanup_network_devices_thread.start()

if __name__ == '__main__':
	main()
