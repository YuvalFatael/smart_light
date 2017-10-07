# Import SDK packages
from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient


def customCallback(client, userdata, message):
	print("Received a new message: ")
	print(message.payload)
	print("from topic: ")
	print(message.topic)
	print("--------------\n\n")

def mqtt_connect():
# For certificate based connection
	myMQTTClient = AWSIoTMQTTClient("light") # Todo: all these should be environment vars
	# For TLS mutual authentication
	myMQTTClient.configureEndpoint("audsodu4ke8z4.iot.us-west-2.amazonaws.com", 8883)
	myMQTTClient.configureCredentials("certs/root-CA.crt", "certs/private.key", "certs/cert.pem")

	myMQTTClient.configureOfflinePublishQueueing(-1)  # Infinite offline Publish queueing
	myMQTTClient.configureDrainingFrequency(2)  # Draining: 2 Hz
	myMQTTClient.configureConnectDisconnectTimeout(10)  # 10 sec
	myMQTTClient.configureMQTTOperationTimeout(5)  # 5 sec

	# Todo: try catch?
	myMQTTClient.connect()
	myMQTTClient.subscribe("hello", 1, customCallback)
	#myMQTTClient.publish("test", "hey this is a message", 0)
	# myMQTTClient.unsubscribe("test")
	#myMQTTClient.disconnect()


def main():
	# Connect to Amazon's MQTT service
	mqtt_connect()

	# Send Hello Message


if __name__ == '__main__':
	main()
