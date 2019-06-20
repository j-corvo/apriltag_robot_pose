#!/usr/bin/python

# Estimate the absolute pose a robot based on the position of detected AprilTag markers
# Provisorily broadcast the transform of robot base w.r.t. map
# Author: Roberto Zegers R.
# Date: 2019 June

import rospy
from apriltags_ros.msg import AprilTagDetection, AprilTagDetectionArray
from geometry_msgs.msg import Pose, PoseStamped, TransformStamped
import tf.transformations as tfm
import numpy as np
import tf
import tf2_ros

## Global variables
nrTfRetrys = 1
retryTime = 0.05
rospy.init_node('apriltag_robot_pose', log_level=rospy.INFO, anonymous=False)
# Initializes a tf listener
lr = tf.TransformListener()
# Initializes a tf broadcaster for robot base w.r.t. map transform
br = tf2_ros.TransformBroadcaster()

def main():
    rospy.Subscriber("/tag_detections", AprilTagDetectionArray, apriltag_callback, queue_size = 1)
    rospy.sleep(1)
    try:
        rospy.spin()
    except KeyboardInterrupt:
        rospy.logwarn("Shutting down ROS AR Tag Robot Pose Estimator")

def pose2poselist(pose):
    return [pose.pose.position.x, pose.pose.position.y, pose.pose.position.z, pose.pose.orientation.x, pose.pose.orientation.y, pose.pose.orientation.z, pose.pose.orientation.w]

def transformPose(lr, pose, sourceFrame, targetFrame):
    '''
    Converts a pose represented as a list in the sourceFrame
    to a pose represented as a list in the targetFrame frame
    '''
    _pose = PoseStamped()
    _pose.header.frame_id = sourceFrame
    if len(pose) == 6:
        pose.append(0)
        pose[3:7] = tfm.quaternion_from_euler(pose[3], pose[4], pose[5]).tolist()

    _pose.pose.position.x = pose[0]
    _pose.pose.position.y = pose[1]
    _pose.pose.position.z = pose[2]
    _pose.pose.orientation.x = pose[3]
    _pose.pose.orientation.y = pose[4]
    _pose.pose.orientation.z = pose[5]
    _pose.pose.orientation.w = pose[6]

    for i in range(nrTfRetrys):
        try:
            t = rospy.Time(0)
            _pose.header.stamp = t
            # converts a Pose object from its reference frame to a Pose object in the frame targetFrame
            _pose_target = lr.transformPose(targetFrame, _pose)
            p = _pose_target.pose.position
            o = _pose_target.pose.orientation
            return [p.x, p.y, p.z, o.x, o.y, o.z, o.w]
        except Exception as ex:
            rospy.logwarn(ex.message)
            rospy.sleep(retryTime)

    return None

def xyzquat_from_matrix(matrix):
    return tfm.translation_from_matrix(matrix).tolist() + tfm.quaternion_from_matrix(matrix).tolist()

def matrix_from_xyzquat(arg1, arg2=None):
    return matrix_from_xyzquat_np_array(arg1, arg2).tolist()

def matrix_from_xyzquat_np_array(arg1, arg2=None):
    if arg2 is not None:
        translate = arg1
        quaternion = arg2
    else:
        translate = arg1[0:3]
        quaternion = arg1[3:7]

    return np.dot(tfm.compose_matrix(translate=translate) ,
                   tfm.quaternion_matrix(quaternion))

def invPoselist(poselist):
    return xyzquat_from_matrix(np.linalg.inv(matrix_from_xyzquat(poselist)))

def broadcastRobotPoseTransform(br, pose=[0,0,0,0,0,0,1], child_frame_id='obj', parent_frame_id='map', npub=1):
    '''
    Converts from a representation of a pose as a list to a TransformStamped object (translation and rotation (Quaternion) representation)
    Then broadcasts that TransformStamped object
    Note:
    In Rviz it will be shown as an arrow from the robot base (child) to the map (parent)
    In RQT it will be shown as an arrow from the map (parent) to the robot base (child)
    '''
    if len(pose) == 7:
        quaternion = tuple(pose[3:7])
    elif len(pose) == 6:
        quaternion = tfm.quaternion_from_euler(*pose[3:6])
    else:
        rospy.logerr("Bad length of pose")
        return None

    position = tuple(pose[0:3])
    # Initializes an empty TransformStamped object (should it be global?)
    ts_base_wrt_map = TransformStamped()
    ## Fill in TransformStamped object
    # Stamps the transform with the current time
    ts_base_wrt_map.header.stamp = rospy.Time.now()
    # Sets the frame ID of the transform to the map frame
    ts_base_wrt_map.header.frame_id = parent_frame_id
    # Sets the child frame ID to 'robot_footprint'
    ts_base_wrt_map.child_frame_id = child_frame_id
    # Fill in coordinates
    ts_base_wrt_map.transform.translation.x = pose[0]
    ts_base_wrt_map.transform.translation.y = pose[1]
    ts_base_wrt_map.transform.translation.z = pose[2]
    ts_base_wrt_map.transform.rotation.x = quaternion[0]
    ts_base_wrt_map.transform.rotation.y = quaternion[1]
    ts_base_wrt_map.transform.rotation.z = quaternion[2]
    ts_base_wrt_map.transform.rotation.w = quaternion[3]

    for j in range(npub):
        # Broadcast the transform of robot base w.r.t. map
        br.sendTransform(ts_base_wrt_map)
        rospy.sleep(0.01)

def averagePose(pose_list):
    '''
    Calculates the averge pose from a list of poses
    Position is the average of all estimated positions
    Orientation uses the orientation of the first detected marker
    '''
    avg_pose = []
    avg_pose.append(np.mean([pose[0] for pose in pose_list]))
    avg_pose.append(np.mean([pose[1] for pose in pose_list]))
    avg_pose.append(np.mean([pose[2] for pose in pose_list]))
    # Use the orientation of the first detected marker
    avg_pose.extend(pose_list[0][3:7])
    return avg_pose

def apriltag_callback(data):
    # rospy.logdebug(rospy.get_caller_id() + "I heard %s", data)
    if data.detections:
        poselist_base_wrt_map = []
        for detection in data.detections:
            tag_id = detection.id  # tag id
            rospy.logdebug("Tag ID detected: %s \n", tag_id)
            child_frame_id = "tag_" + str(tag_id)
            # Check that detected tag corresponds to one of the tags whos position is being broadcasted by the static transform broadcaster node
            if lr.frameExists(child_frame_id):
                try:
                    poselist_tag_wrt_camera = pose2poselist(detection.pose)
                    rospy.logdebug("poselist_tag_wrt_camera: \n %s \n", poselist_tag_wrt_camera)

                    # Calculate transform of tag w.r.t. robot base (in Rviz arrow points from tag (child) to robot base(parent))
                    poselist_tag_wrt_base = transformPose(lr, poselist_tag_wrt_camera, 'camera', 'robot_footprint')
                    rospy.logdebug("transformPose(lr, poselist_tag_wrt_camera, 'camera', 'robot_footprint'): \n %s \n", poselist_tag_wrt_base)

                    # Calculate transform of robot base w.r.t. tag (in Rviz arrow points from robot base (child) to tag(parent))
                    poselist_base_wrt_tag = invPoselist( poselist_tag_wrt_base)
                    rospy.logdebug("invPoselist( poselist_tag_wrt_base): \n %s \n", poselist_base_wrt_tag)

                    # Calculate transform of robot base w.r.t. map (in Rviz arrow points from robot base (child) to map (parent)), returns pose of robot in the map coordinates
                    poselist_base_wrt_map.append(transformPose(lr, poselist_base_wrt_tag, child_frame_id, targetFrame = 'map'))
                    rospy.logdebug("transformPose(lr, poselist_base_wrt_tag, sourceFrame = '%s', targetFrame = 'map'): \n %s \n", child_frame_id, poselist_base_wrt_map[-1])

	        except (tf.LookupException, tf.ConnectivityException, tf.ExtrapolationException), e:
		    rospy.logerr(e)
		    continue
            else:
                rospy.logwarn("No tf frame with name %s found. Check that the detected tag ID is part of the transforms that are being broadcasted by the static transform broadcaster.", child_frame_id)

        for counter, robot_pose in enumerate(poselist_base_wrt_map):
            rospy.logdebug("\n Robot pose estimation nr. %s: %s \n",str(counter), robot_pose)

        estimated_avg_pose = averagePose(poselist_base_wrt_map)
        # Broadcasts transform of robot base w.r.t. map or pose of robot in the map coordinates
        broadcastRobotPoseTransform(br, pose = estimated_avg_pose, child_frame_id = 'robot_footprint', parent_frame_id = 'map')
        rospy.loginfo("\n Robot's estimated avg. pose from all AR tags detected:\n %s \n", estimated_avg_pose)

if __name__=='__main__':
    main()
