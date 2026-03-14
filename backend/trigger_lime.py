import subprocess

def trigger_lime():
    print("Triggering LIME notebook on Kaggle...")

    # Corrected for Kaggle CLI 2.0
    result = subprocess.run(
        ["kaggle", "kernels", "push", "--path", "kaggle_lime"],
        capture_output=True,
        text=True
    )

    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)

    # Optional: extract kernel URL
    for line in result.stdout.splitlines():
        if "https://www.kaggle.com/kernels/" in line:
            print("Kernel URL:", line)

if __name__ == "__main__":
    trigger_lime()