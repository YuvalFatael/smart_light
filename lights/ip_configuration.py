# Global Vars:
WIDE_RANGE = True

if WIDE_RANGE: # Wide scene parameters
    #Tracker:
    TRACKER_SEARCH_WINDOW = 2.5
    TRACKER_SIGMA_FACTOR = 0.125
    TRACKER_INTERP_FACTOR = 0.02#75
    TRACKER_SIGMA = 0.5

  
    #Detection:
    ABSDIFF_THRESHOLD = 50#25
    PERSON_ASPECT_RATIO = 1.2
    ALPHA_BLENDING = 0.00
    CLOSING_KERNEL = (10, 15)
    MARGINS_IGNORANCE_TO_DETECT = 20
    MARGINS_IGNORANCE_TO_DECISION = 5
    MIN_BLOB_AREA = 500
    GAUSSIAN_WIDTH = (9, 9)

    # More
    CAMERA_FOV = 53.5
    DISTANCE_FROM_DETECTIONS = 5 #in meters
    IMAGE_WIDTH = 320 #pixels




#else:# Narrow scene parameters
    #TODO

