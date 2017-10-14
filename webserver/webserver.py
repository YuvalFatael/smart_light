from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient

def customCallback(client, userdata, message):
	print("Received a new message: ")
	print(message.payload.decode("utf-8"))
	print("from topic: ")
	print(message.topic)
	print("--------------\n\n")

myMQTTClient = AWSIoTMQTTClient("client")
myMQTTClient.configureEndpoint("audsodu4ke8z4.iot.us-west-2.amazonaws.com", 8883)
myMQTTClient.configureCredentials("certs/root-CA.crt", "certs/private.key", "certs/cert.pem")

myMQTTClient.configureOfflinePublishQueueing(-1)  # Infinite offline Publish queueing
myMQTTClient.configureDrainingFrequency(2)  # Draining: 2 Hz
myMQTTClient.configureConnectDisconnectTimeout(10)  # 10 sec
myMQTTClient.configureMQTTOperationTimeout(5)  # 5 sec

myMQTTClient.connect()
myMQTTClient.subscribe("control", 1, customCallback)

while True:
    pass