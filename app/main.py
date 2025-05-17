from flask import Flask, jsonify, request
from flasgger import Swagger, swag_from
import os
import boto3
from botocore.exceptions import ClientError

app = Flask(__name__)
swagger_config = {
    "headers": [],
    "specs": [
        {
            "endpoint": 'swagger',
            "route": '/swagger.json',
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "title": "Loadsmart SRE API"
}
swagger = Swagger(app, config=swagger_config)

# AWS Configuration (using IAM roles)
REGION_NAME = os.environ.get("AWS_REGION", "us-east-1")  # Default region

# Initialize AWS clients (outside route handlers for efficiency)
ec2 = boto3.client(
    'ec2',
    region_name=REGION_NAME,
)
elb_client = boto3.client(
    'elbv2',
    region_name=REGION_NAME,
)


@app.route('/healthcheck!')
@swag_from('swagger_files/healthcheck.yml')
def healthcheck():
    """
    API health check
    """
    return jsonify({"status": "up"}), 200



def get_instance_info(instance_id):
    """
    Retrieves information about a specific EC2 instance.

    Args:
        instance_id (str): The ID of the EC2 instance.

    Returns:
        dict: A dictionary containing instance information, or None if the instance is not found.
    """
    try:
        response = ec2.describe_instances(InstanceIds=[instance_id])
        if response and response['Reservations']:
            instance = response['Reservations'][0]['Instances'][0]
            return {
                'instanceId': instance['InstanceId'],
                'instanceType': instance['InstanceType'],
                'launchDate': instance['LaunchTime'].isoformat()
            }
        else:
            return None
    except ClientError as e:
        print(f"Error describing instance {instance_id}: {e}")
        return None



def get_target_group_arn(elb_name):
    """
    Retrieves the ARN of the target group associated with a given load balancer.

    Args:
        elb_name (str): The name of the load balancer.

    Returns:
        str: The ARN of the target group, or None if not found.
    """
    try:
        response = elb_client.describe_load_balancers(Names=[elb_name]) # Use elb_name
        if response and response['LoadBalancers']:
            load_balancer = response['LoadBalancers'][0]
            # Assumes there is one target group associated with the load balancer.
            #  This needs to be modified to handle multiple target groups.
            target_group_response = elb_client.describe_target_groups(LoadBalancerArns=[load_balancer['LoadBalancerArn']])

            if target_group_response and target_group_response['TargetGroups']:
                return target_group_response['TargetGroups'][0]['TargetGroupArn']
            else:
                return None

        else:
            return None
    except ClientError as e:
        print(f"Error describing load balancer {elb_name}: {e}")
        return None



@app.route('/elb/alb-ls', methods=['GET']) # Hardcoded elb_name
@swag_from('swagger_files/list_machines_elb.yml')
def list_machines_elb():
    """
    List machines attached to the default load balancer
    """
    target_group_arn = get_target_group_arn("default-alb") # Hardcoded elb_name
    if not target_group_arn:
        return jsonify({"error": "Load balancer default-alb does not exist or has no target group."}), 404

    try:
        response = elb_client.describe_target_health(TargetGroupArn=target_group_arn)
        target_health_descriptions = response['TargetHealthDescriptions']
        instances = []
        for target_health in target_health_descriptions:
            instance_id = target_health['Target']['Id']
            instance_info = get_instance_info(instance_id)  # Reuse the function
            if instance_info:
                instances.append(instance_info)
        return jsonify(instances), 200
    except ClientError as e:
        return jsonify({"error": str(e)}), 500



@app.route('/elb/alb-ls', methods=['POST']) # Hardcoded elb_name
@swag_from('swagger_files/attach_instance.yml')
def attach_instance():
    """
    Attach an instance on the default load balancer
    """
    target_group_arn = get_target_group_arn("default-alb") # Hardcoded elb_name
    if not target_group_arn:
        return jsonify({"error": "Load balancer default-alb does not exist or has no target group."}), 404

    data = request.get_json()
    if not data or 'instanceId' not in data:
        return jsonify({"error": "Invalid request format.  Expected: {'instanceId': 'instance_id'}"}), 400

    instance_id = data['instanceId']
    instance_info = get_instance_info(instance_id)
    if not instance_info:
        return jsonify({"error": f"Instance {instance_id} does not exist."}), 400

    try:
        response = elb_client.register_targets(
            TargetGroupArn=target_group_arn,
            Targets=[
                {
                    'Id': instance_id,
                    'Port': 80,  #  Assuming port 80 for the instance
                },
            ],
        )
        return jsonify(instance_info), 201 # Return the instance info
    except ClientError as e:
        if e.response['Error']['Code'] == 'DuplicateTargetFound':
            return jsonify({"error": f"Instance {instance_id} is already attached to the load balancer."}), 409
        return jsonify({"error": str(e)}), 500



@app.route('/elb/alb-ls', methods=['DELETE']) # Hardcoded elb_name
@swag_from('swagger_files/detach_instance.yml')
def detach_instance():
    """
    Detach an instance from the default load balancer
    """
    target_group_arn = get_target_group_arn("default-alb") # Hardcoded elb_name
    if not target_group_arn:
        return jsonify({"error": "Load balancer default-alb does not exist or has no target group."}), 404
    data = request.get_json()
    if not data or 'instanceId' not in data:
        return jsonify({"error": "Invalid request format. Expected: {'instanceId': 'instance_id'}"}), 400
    instance_id = data['instanceId']
    instance_info = get_instance_info(instance_id)
    if not instance_info:
        return jsonify({"error": f"Instance {instance_id} does not exist."}), 400

    try:
        response = elb_client.deregister_targets(
            TargetGroupArn=target_group_arn,
            Targets=[
                {
                    'Id': instance_id,
                    'Port': 80,  # Assuming port 80
                },
            ],
        )
        return jsonify(instance_info), 201 # return instance info
    except ClientError as e:
        if e.response['Error']['Code'] == 'TargetNotFound':
            return jsonify({"error": f"Instance {instance_id} is not attached to the load balancer."}), 409
        return jsonify({"error": str(e)}), 500



if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=80)

