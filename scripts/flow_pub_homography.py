import numpy as np
import picamera
import picamera.array
import cv2
import rospy
import time
import sys
from h2rMultiWii import MultiWii
from picam_flow_class import AnalyzeFlow
from pidrone_pkg.msg import axes_err, Mode, ERR
from cv_bridge import CvBridge, CvBridgeError
from sensor_msgs.msg import Image, Range
from geometry_msgs.msg import PoseStamped, Point
from std_msgs.msg import Empty
import rospy
import tf
import copy
from pyquaternion import Quaternion
import time
from copy import deepcopy
from cv_bridge import CvBridge, CvBridgeError
import sys
from pid_class import PIDaxis

keynumber = 5

class AnalyzeHomography(picamera.array.PiMotionAnalysis):

    def compose_pose(RT):
        pos = PoseStamped()
        quat_r = tf.transformations.quaternion_from_matrix(RT)
        pos.header.frame_id = 'world'
        pos.header.seq += 1
        pos.header.stamp = rospy.Time.now()
        pos.pose.position.x = RT[0][3]
        pos.pose.position.y = RT[1][3]
        pos.pose.position.z = RT[2][3]
        pos.pose.orientation.x = quat_r[0]
        pos.pose.orientation.y = quat_r[1]
        pos.pose.orientation.z = quat_r[2]
        pos.pose.orientation.w = quat_r[3]

        return pos

    def get_H(self, curr_img):
        global first_kp, first_des
        curr_kp, curr_des = orb.detectAndCompute(curr_img,None)

        good = []
        flann = cv2.FlannBasedMatcher(index_params, search_params)

        if first_des is not None and curr_des is not None and len(first_des) > 3 and len(curr_des) > 3:
            matches = flann.knnMatch(first_des,curr_des,k=2)
            # store all the good matches as per Lowe's ratio test.
            for test in matches:
                if len(test) > 1:
                    m, n = test
                    if m.distance < 0.7*n.distance:
                         good.append(m)

            H = None
            if len(good) > min_match_count:
                src_pts = np.float32([first_kp[m.queryIdx].pt for m in good]).reshape(-1,1,2) dst_pts = np.float32([curr_kp[m.trainIdx].pt for m in good]).reshape(-1,1,2)

                H, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC,5.0)

            return H

    else:
        print "Not enough matches are found - %d/%d" % (len(good),min_match_count)
        return None

    def get_RT(self, H):
        retval, Rs, ts, norms = cv2.decomposeHomographyMat(H,
                camera_matrix)
        min_index = 0
        min_z_norm = 0
        for i in range(len(Rs)):
            if norms[i][2] < min_z_norm:
                min_z_norm = norms[i][2]
                min_index = i

        T = ts[min_index] * z

        return Rs[min_index], T, norms[min_index]

    def write(self, data):
        cv2.imshow("data", data)
        cv2.waitKey(1)
        img = data
        if self.first:
            self.first = False
            self.first_kp, self.first_des = self.orb.detectAndCompute(first_img, None)
            self.prev_time = rospy.get_time()
        else:
            curr_time = rospy.get_time()
            H = get_H(img)
            if H is not None:
                R, t, n = self.get_RT(H)
                RT = np.identity(4)
                RT[0:3, 0:3] = R[0:3, 0:3]
                if np.linalg.norm(t) < 50:
                    RT[0:3, 3] = t.T[0]
                new_pos = self.compose_pose(RT)
                self.smoothed_pos.header = new_pos.header
                self.smoothed_pos.pose.position.x = (1. - self.alpha) * self.smoothed_pos.pose.position.x + self.alpha * new_pos.pose.position.x
                self.smoothed_pos.pose.position.y = (1. - self.alpha) * self.smoothed_pos.pose.position.y + self.alpha * new_pos.pose.position.y
                mode = Mode()
                mode.mode = 5
                self.lr_err.err = self.smoothed_pos.pose.position.x
                self.fb_err.err = self.smoothed_pos.pose.position.y
                mode.x_velocity = self.lr_pid.step(self.lr_err.err, self.prev_time - curr_time)
                mode.y_velocity = self.fb_pid.step(self.fb_err.err, self.prev_time - curr_time)
                print 'lr', mode.x_velocity, 'fb', mode.y_velocity
                self.prev_time = curr_time
                self.pospub.publish(mode)
            else:
                mode = Mode()
                mode.mode = 5
                mode.x_velocity = 0
                mode.y_velocity = 0
                print "LOST"
                self.prev_time = curr_time
                self.pospub.publish(mode)

        
    def setup(self, camera_wh = (320,240), pub=None, flow_scale = 16.5):
        self.first_kp = None
        self.first_des = None
        self.first = True
        self.orb = cv2.ORB_create(nfeatures=500, nlevels=8, scaleFactor=1.1)
        self.alpha = 0.6
        self.lr_err = ERR()
        self.fb_err = ERR()
        self.prev_time = None
        self.pospub = rospy.Publisher('/pidrone/set_mode', Mode, queue_size=1)
        self.smoothed_pos = PoseStamped()
        self.lr_pid = PIDaxis(-0.22, -0., -0., midpoint=0, control_range=(-15., 15.))
        self.fb_pid = PIDaxis(0.22, 0., 0., midpoint=0, control_range=(-15., 15.))

if __name__ == '__main__':
    rospy.init_node('flow_pub')
    velpub= rospy.Publisher('/pidrone/plane_err', axes_err, queue_size=1)
    imgpub = rospy.Publisher("/pidrone/camera", Image, queue_size=1)
    try:
        velocity = axes_err()
        bridge = CvBridge()
        with picamera.PiCamera(framerate=90) as camera:
            with AnalyzeFlow(camera) as flow_analyzer:
                with AnalyzeHomography(camera) as homography_analyzer:
                    camera.resolution = (320, 240)
                    flow_analyzer.setup(camera.resolution)
                    camera.start_recording(homography_analyzer, format='h264', motion_output=flow_analyzer)
                    i = 0
                    while not rospy.is_shutdown():
                        velocity.x.err = flow_analyzer.x_motion 
                        velocity.y.err = flow_analyzer.y_motion
                        velocity.z.err = flow_analyzer.z_motion
                        camera.wait_recording(1/100.0)
                        velpub.publish(velocity)

                    camera.stop_recording()
        print "Shutdown Recieved"
        sys.exit()
    except Exception as e:
        raise 