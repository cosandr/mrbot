import pytest
import os


@pytest.mark.asyncio
async def test_pdb():
    from kubernetes_asyncio import client, config
    from kubernetes_asyncio.client.api_client import ApiClient

    # Running in Kubernetes
    try:
        config.load_incluster_config()
    except config.config_exception.ConfigException:
        await config.load_kube_config()

    # TODO: Move to config
    namespace = os.getenv("POD_NAMESPACE", "default")
    selector = os.getenv("POD_SELECTOR", "app.kubernetes.io/instance=mrbot")
    label_key = os.getenv("BUSY_LABEL_KEY", "is-busy")
    label_value = os.getenv("BUSY_LABEL_VALUE", "true")
    add_patch = [
        {
            "op": "add",
            "path": f"/metadata/labels/{label_key}",
            "value": label_value
        }
    ]

    remove_patch = [
        {
            "op": "remove",
            "path": f"/metadata/labels/{label_key}"
        }
    ]

    async with ApiClient() as api:
        v1 = client.CoreV1Api(api)
        # Get all pods in namespace
        ret = await v1.list_namespaced_pod(namespace, label_selector=selector)

        core = client.CoreApi(api)
        test = await core.get_api_versions()
        # Add label
        for pod in ret.items:
            pod_name = pod.metadata.name
            label = getattr(pod.metadata, "labels", {})
            try:
                await v1.patch_namespaced_pod(name=pod_name, namespace=namespace, body=add_patch)
                print(f"Label '{label_key}={label_value}' successfully added to pod {pod_name}.")
            except client.exceptions.ApiException as e:
                print(f"Error adding label: {e}")

        # Remove label
        for pod in ret.items:
            pod_name = pod.metadata.name
            try:
                await v1.patch_namespaced_pod(name=pod_name, namespace=namespace, body=remove_patch)
                print(f"Label '{label_key}' successfully removed from pod {pod_name}.")
            except client.exceptions.ApiException as e:
                if e.status == 422:
                    print(f"Label '{label_key}' does not exist on pod {pod_name}.")
                else:
                    print(f"Error removing label: {e}")
