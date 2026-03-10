import subprocess

def trigger_kaggle():

    try:
        result = subprocess.run(
            ["kaggle", "kernels", "push"],
            cwd="kaggle_generator",
            capture_output=True,
            text=True
        )

        print("STDOUT:\n", result.stdout)
        print("STDERR:\n", result.stderr)

    except Exception as e:
        print("Error:", e)


if __name__ == "__main__":
    trigger_kaggle()