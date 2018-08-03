import sys
import rospy
import picamera
from analyze_flow import AnalyzeFlow
from analyze_phase import AnalyzePhase

def main():
    rospy.init_node('camera_controller')
    print 'Vision started'
    try:
        with picamera.PiCamera(framerate=90) as camera:
            camera.resolution = (320, 240)
            with AnalyzePhase(camera) as phase_analyzer:
                with AnalyzeFlow(camera) as flow_analyzer:
                    # run the setup functions for each of the image callback classes
                    flow_analyzer.setup(camera.resolution)
                    phase_analyzer.setup(camera.resolution)
                    # start the recordings for the image and the motion vectors
                    camera.start_recording("/dev/null", format='h264', splitter_port=1, motion_output=flow_analyzer)
                    camera.start_recording(phase_analyzer, format='bgr', splitter_port=2)
                     # nonblocking wait
                    while not rospy.is_shutdown(): camera.wait_recording(1/100.0)

                camera.stop_recording(splitter_port=1)  # stop recording both the flow
            camera.stop_recording(splitter_port=2)      # and the images

        print "Shutdown Recieved"
        sys.exit()

    except Exception as e:
        raise

if __name__ == '__main__':
    main()