import sagemaker
import boto3
import os
import requests
import json
from datetime import datetime
from time import strftime, gmtime, sleep

# Release Tracker Code

release_tracker_host = "https://internal.circleci.com/"
release_tracker_headers = {
    "accept": "application/json",
    "Authorization": os.environ["CCI_INTEGRATION_TOKEN"],
    "Content-Type": "application/json",
}


# Formatted rt style
def get_current_datetime():
    return f"{datetime.now().isoformat()}Z"


# TODO set the other things like pipeline id, workflowid, etc... We should be able to do that
# register the compenent with the release tracker
# use this to update the current version
def upsert_component(slug, display_name, current_version_name, current_version_image):
    print(
        f"slug: {slug}, display_name: {display_name}, current_version_name: {current_version_name}, current_version_image: {current_version_image}"
    )
    url = f"{release_tracker_host}release-agent/v1/component"
    # we need to pass in the name,
    current_versions = [
        {
            "desired_replicas": 1,
            "images": [current_version_image],
            "job_number": 7,
            "name": current_version_name,
            "pipeline_id": "fe37088f-9907-4172-b298-dfcbca78fb65",
            "workflow_id": "b9944239-8e68-448b-a7f9-d51e49deff8f",
        }
    ]

    data = {
        "current_versions": current_versions,
        # Display Name
        "name": display_name,
        "project_id": "ba4168c3-1b78-4ecf-9e33-39f9174337ed",
        # identifier
        "slug": slug,
    }

    response = requests.put(url, headers=release_tracker_headers, data=json.dumps(data))
    return response.status_code


# TODO right now we are encoding to one step, but we can expand to more steps
# ReleaseStatus = "RUNNING"
# ReleaseStatus = "SUCCESS"
# ReleaseStatus = "FAILED"
# ReleaseStatus = "UNKNOWN"
# ReleaseStatus = "CANCELED"
# StepStatus = "PENDING"
# StepStatus = "PAUSED"
# StepStatus = "RUNNING"
# StepStatus = "SUCCESS"
# StepStatus = "FAILED"
# StepStatus = "CANCELED"
def upsert_release(
    slug,
    release_status,
    step_status,
    type,
    current_version_name,
    current_version_image,
    endtime=None,
):
    print(
        f"slug: {slug}, release_status: {release_status}, step_status: {step_status}, type: {type}, current_version_name: {current_version_name}, current_version_image: {current_version_image}, endtime: {endtime}"
    )
    url = f"{release_tracker_host}release-agent/v1/release"
    data = {
        "command_id": "00000000-0000-0000-0000-000000000000",
        "component_slug": slug,
        "detected_at": "2023-11-05T012:30:42.539Z",
        "status": release_status,
        "steps": [
            {
                "config": "string",
                "number": 0,
                "started_at": "2023-11-05T06:31:42.540Z",  # get_current_datetime(),
                "status": step_status,
                "type": type,
            }
        ],
        "target_version": {
            "desired_replicas": 1,
            "images": current_version_image,
            "job_number": 7,
            "name": "busy-bee-1.0.2",  # current_version_name,
            "pipeline_id": "fe37088f-9907-4172-b298-dfcbca78fb65",
            "workflow_id": "b9944239-8e68-448b-a7f9-d51e49deff8f",
        },
        "type": "DEPLOYMENT",
    }

    if endtime:
        data["steps"][0]["ended_at"] = endtime

    response = requests.put(url, headers=release_tracker_headers, data=json.dumps(data))
    response.raise_for_status()

    return response.status_code


######

# Environment variables
# See this link for more details: https://circleci.com/docs/set-environment-variable/
bucket = "circleci-sagemaker"
region_name = "us-east-1"
model_name = os.environ["MODEL_NAME"]
model_description = os.environ["MODEL_DESC"]
role_arn = os.environ["SAGEMAKER_EXECUTION_ROLE_ARN"]
endpoint_instance_type = "ml.t2.medium"
endpoint_instance_count = 1
current_time = strftime("%Y-%m-%d-%H-%M-%S", gmtime())


# Init the component - do the get for current - if it exists, great, if not, create
# todo

# Set up the sessions and clients we will need for this step
boto_session = boto3.Session(region_name=region_name)
sagemaker_client = boto_session.client(service_name="sagemaker")
sagemaker_runtime_client = boto_session.client(service_name="sagemaker-runtime")
sagemaker_session = sagemaker.Session(
    boto_session=boto_session,
    sagemaker_client=sagemaker_client,
    sagemaker_runtime_client=sagemaker_runtime_client,
    default_bucket=bucket,
)


# Get the latest approved model package of the model group in question
model_package_arn = sagemaker_client.list_model_packages(
    ModelPackageGroupName=model_name,
    ModelApprovalStatus="Approved",
    SortBy="CreationTime",
    SortOrder="Descending",
)["ModelPackageSummaryList"][0]["ModelPackageArn"]

# Get a list of existing models with model_name
models_list = sagemaker_client.list_models(NameContains=model_name)["Models"]

# Create the model
timed_model_name = f"{model_name}-{current_time}"
container_list = [{"ModelPackageName": model_package_arn}]

create_model_response = sagemaker_client.create_model(
    ModelName=timed_model_name, ExecutionRoleArn=role_arn, Containers=container_list
)
print(f"Created model ARN: {create_model_response['ModelArn']}")


# Get a list of existing endpoint configs with model_name
endpoint_configs_list = sagemaker_client.list_endpoint_configs(NameContains=model_name)[
    "EndpointConfigs"
]
print(f"Endpoint configs: {endpoint_configs_list}")

# Create endpoint config
create_endpoint_config_response = sagemaker_client.create_endpoint_config(
    EndpointConfigName=timed_model_name,
    ProductionVariants=[
        {
            "InstanceType": endpoint_instance_type,
            "InitialVariantWeight": 1,
            "InitialInstanceCount": endpoint_instance_count,
            "ModelName": timed_model_name,
            "VariantName": "AllTraffic",
        }
    ],
)
print(
    f"Created endpoint config ARN: {create_endpoint_config_response['EndpointConfigArn']}"
)


# Get a list of existing endpoints with model_name
endpoints_list = sagemaker_client.list_endpoints(NameContains=model_name)["Endpoints"]

try:
    print(f"pre deploy - upsert_release {model_name}")
    upsert_release(
        slug=f"sagemaker.{model_name}",
        release_status="RUNNING",
        step_status="RUNNING",
        type="WAITING_FOR_AVAILABILITY",
        current_version_name=f"{model_name}",
        current_version_image=[f"modelArn: {create_model_response['ModelArn']}"],
    )
# TODO better error handling!
except requests.exceptions.HTTPError as err:
    print(err)
    raise

    if err.response.status_code == 400:
        # This is the create if it doesn't exist. Not perfect, but we infer from the 400
        # because we dont have a way for API to get this. just BFF
        print(f"component doesnt exist, so creating {model_name}")
        upsert_component(
            slug=f"sagemaker.{model_name}",
            display_name=f"sagemaker.{model_name}",
            current_version_name="initialize",
            current_version_image="initialize",
        )
        upsert_release(
            slug=f"sagemaker.{model_name}",
            release_status="RUNNING",
            step_status="RUNNING",
            type="WAITING_FOR_AVAILABILITY",
            current_version_name=f"{model_name}",
            current_version_image=[f"modelArn: {create_model_response['ModelArn']}"],
        )

    else:
        print(f"HTTP error occurred with status code: {err.response.status_code}")
        print(err.response.text)

# Create or update the endpoint
if endpoints_list:
    create_update_endpoint_response = sagemaker_client.update_endpoint(
        EndpointName=model_name, EndpointConfigName=timed_model_name
    )
else:
    create_update_endpoint_response = sagemaker_client.create_endpoint(
        EndpointName=model_name, EndpointConfigName=timed_model_name
    )

# Wait for endpoint ot be InService status
describe_endpoint_response = sagemaker_client.describe_endpoint(EndpointName=model_name)
while describe_endpoint_response["EndpointStatus"] != "InService":
    print(describe_endpoint_response["EndpointStatus"])
    sleep(30)
    describe_endpoint_response = sagemaker_client.describe_endpoint(
        EndpointName=model_name
    )

endpoint_arn = create_update_endpoint_response["EndpointArn"]
print(f"Created endpoint ARN: {endpoint_arn}")

print(f"upsert_release {model_name}")
upsert_release(
    slug=f"sagemaker.{model_name}",
    release_status="SUCCESS",
    step_status="SUCCESS",
    endtime=get_current_datetime(),
    type="WAITING_FOR_AVAILABILITY",
    current_version_name=f"{model_name}",
    current_version_image=[
        f"modelArn: {create_model_response['ModelArn']}",
        f"endpointArn: {endpoint_arn}",
    ],
)

print(f"upsert_component {model_name}")
upsert_component(
    slug=f"sagemaker.{model_name}",
    display_name=f"sagemaker.{model_name}",
    current_version_name=f"{timed_model_name}",
    current_version_image=endpoint_arn,
)

# Cleanup
# If model already existed, delete old versions
if models_list:
    for model in models_list:
        delete_model_name = model["ModelName"]
        sagemaker_client.delete_model(ModelName=delete_model_name)
        print(f"Model {delete_model_name} deleted.")

# If endpoint config already existed, delete old versions
if endpoint_configs_list:
    for endpoint_config in endpoint_configs_list:
        delete_endpoint_config_name = endpoint_config["EndpointConfigName"]
        sagemaker_client.delete_endpoint_config(
            EndpointConfigName=delete_endpoint_config_name
        )
        print(f"Endpoint config {delete_endpoint_config_name} deleted.")
