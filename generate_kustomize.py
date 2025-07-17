#!/usr/bin/env python3
import argparse, os, yaml, glob
from pathlib import Path
from ruamel.yaml import YAML

yaml_loader = YAML()

def extract_deployments(glob_patterns):
    deployment_files = []

    for pattern in glob_patterns:
        for file_path in glob.glob(pattern, recursive=True):
            with open(file_path, 'r') as f:
                try:
                    docs = list(yaml.safe_load_all(f))
                    for doc in docs:
                        # Handle list of documents at the top level
                        if isinstance(doc, list):
                            for item in doc:
                                if isinstance(item, dict) and item.get('kind') == 'Deployment':
                                    deployment_files.append((file_path, item))
                                    break
                        elif isinstance(doc, dict) and doc.get('kind') == 'Deployment':
                            deployment_files.append((file_path, doc))
                            break
                except yaml.YAMLError as e:
                    print(f"YAML parse error in {file_path}: {e}")
    return deployment_files

def calculate_resources(total_cpu, total_mem, category):
    if category in ['pipeline', 'notebook', 'training-operator']:
        return int(total_cpu * 0.8), int(total_mem * 0.8)
    return int(total_cpu * 0.1), int(total_mem * 0.1)

def to_millicpu(cpu): return f"{cpu}m"
def to_mib(mem): return f"{mem}Mi"

def get_category(name):
    name = name.lower()
    if 'pipeline' in name:
        return 'pipeline'
    elif 'notebook' in name:
        return 'notebook'
    elif 'training-operator' in name:
        return 'training-operator'
    else:
        return 'core'

def patch_deployment(name, cpu, mem):
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": { "name": name },
        "spec": {
            "template": {
                "spec": {
                    "containers": [{
                        "name": name,
                        "resources": {
                            "requests": { "cpu": to_millicpu(cpu//2), "memory": to_mib(mem//2) },
                            "limits": { "cpu": to_millicpu(cpu), "memory": to_mib(mem) },
                        }
                    }]
                }
            }
        }
    }

def write_patch(name, data, category):
    out_path = Path(f"patches/{category}")
    out_path.mkdir(parents=True, exist_ok=True)
    with open(out_path / f"{name}.yaml", 'w') as f:
        yaml_loader.dump(data, f)

def write_kustomization():
    kustomization = {
        "apiVersion": "kustomize.config.k8s.io/v1beta1",
        "kind": "Kustomization",
        "sortOptions": {
            "order": "legacy",
            "legacySortOptions": {
                "orderFirst": [
                    "Namespace",
                    "ResourceQuota",
                    "StorageClass",
                    "CustomResourceDefinition",
                    "MutatingWebhookConfiguration",
                    "ServiceAccount",
                    "PodSecurityPolicy",
                    "NetworkPolicy",
                    "Role",
                    "ClusterRole",
                    "RoleBinding",
                    "ClusterRoleBinding",
                    "ConfigMap",
                    "Secret",
                    "Endpoints",
                    "Service",
                    "LimitRange",
                    "PriorityClass",
                    "PersistentVolume",
                    "PersistentVolumeClaim",
                    "Deployment",
                    "StatefulSet",
                    "CronJob",
                    "PodDisruptionBudget",
                ],
                "orderLast": [
                    "ValidatingWebhookConfiguration",
                ]
            }
        },
        "resources": [
            # Cert-Manager
            "../common/cert-manager/base",
            "../common/cert-manager/kubeflow-issuer/base",
            "../common/istio/istio-crds/base",
            # Istio
            "../common/istio/istio-crds/base",
            "../common/istio/istio-namespace/base",
            "../common/istio/istio-install/overlays/oauth2-proxy",
            # oauth2-proxy
            "../common/oauth2-proxy/overlays/m2m-dex-only",
            # Dex
            "../common/dex/overlays/oauth2-proxy",
            # KNative
            "../common/knative/knative-serving/overlays/gateways",
            "../common/istio/cluster-local-gateway/base",
            # Kubeflow namespace
            "../common/kubeflow-namespace/base",
            # NetworkPolicies
            "../common/networkpolicies/base",
            # Kubeflow Roles
            "../common/kubeflow-roles/base",
            # Kubeflow Istio Resources
            "../common/istio/kubeflow-istio-resources/base",
            # Kubeflow Pipelines
            "../applications/pipeline/upstream/env/cert-manager/platform-agnostic-multi-user",
            # Katib
            "./applications/katib/upstream/installs/katib-with-kubeflow",
            # Central Dashboard
            "../applications/centraldashboard/overlays/oauth2-proxy",
            # Admission Webhook
            "../applications/admission-webhook/upstream/overlays/cert-manager",
            # Jupyter Web App
            "../applications/jupyter/jupyter-web-app/upstream/overlays/istio",
            # Notebook Controller
            "../applications/jupyter/notebook-controller/upstream/overlays/kubeflow",
            # Profiles + KFAM with PSS (Pod Security Standards)
            "../applications/profiles/pss",
            # PVC Viewer
            "../applications/pvcviewer-controller/upstream/base",
            # Volumes Web App
            "../applications/volumes-web-app/upstream/overlays/istio",
            # Training Operator
            "../applications/training-operator/upstream/overlays/kubeflow",
            # User namespace
            "../common/user-namespace/base",
            # KServe
            "../applications/kserve/kserve",
            "../applications/kserve/models-web-app/overlays/kubeflow",
        ],
        "patchesStrategicMerge": []
    }
    for patch in glob.glob("patches/**/*.yaml", recursive=True):
        kustomization["patchesStrategicMerge"].append(f"../{patch}")
    with open("mini-kubeflow/kustomization.yaml", "w") as f:
        yaml_loader.dump(kustomization, f)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cpu", type=int, default=4000)
    parser.add_argument("--mem", type=int, default=10240)
    args = parser.parse_args()

    files = extract_deployments(["common/**/**/*.yaml", "applications/**/**/*.yaml"])
    for path, dep in files:
        name = dep['metadata']['name']
        category = get_category(name)
        cpu, mem = calculate_resources(args.cpu, args.mem, category)
        patch = patch_deployment(name, cpu, mem)
        write_patch(name, patch, category)

    write_kustomization()
    print("✅ Patches & kustomization.yaml generated.")

if __name__ == "__main__":
    main()