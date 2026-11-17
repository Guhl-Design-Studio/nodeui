# Generate an image from Control Center

Use a **Shortcut** control to enter a new prompt in iOS's popup and generate an image without bringing NodeUI to the foreground. Configure the server and workflow once; each tap asks for a fresh prompt.

This requires NodeUI’s updated Share/Shortcuts app build and companion 2.1.1. The new app build is being prepared as iOS 1.3; it is not included in the previously submitted iOS 1.2 build. Download the companion from the [latest release](https://github.com/Guhl-Design-Studio/nodeui/releases/latest).

## Prepare your workflow

1. Install the updated [NodeUI companion](companion.md) on your self-hosted ComfyUI server and restart ComfyUI when its queue is idle. Open NodeUI once, add that server, and allow notifications if you want an image notification.
2. In your text-to-image workflow, add one enabled **Prompt Input** from the **NodeUI** node category on the main canvas. Connect its prompt output to your positive text encoder. In ComfyUI's web editor, convert the encoder's text widget to an input before connecting it. Leave your negative prompt and other settings as desired.
3. Connect the generated image to one enabled **Return Image to NodeUI**, also on the main canvas, and save the workflow to the server. Groups between the prompt and return nodes are supported. No input image is required.

The prompt entered in the popup replaces Prompt Input only for that submission. Your saved workflow and the workflow currently open in NodeUI retain their existing text and settings. The action reloads the server's saved workflow on each run, so save changes before using them from Control Center.

## Create the shortcut

In Apple's **Shortcuts** app, create a shortcut named **Run NodeUI Workflow With Prompt** with these two actions:

1. **Ask for Input**: ask **What would you like to generate?**, with input type **Text**.
2. **Run NodeUI Workflow With Prompt** (the NodeUI action): choose your saved **Workflow**, and set **Prompt** to **Provided Input** from the first action.

The workflow picker shows the server name alongside each workflow. The action returns a job ID immediately after ComfyUI accepts the run; a Show Result action is unnecessary. Cancelling the input popup stops the shortcut before it submits anything.

## Add the Control Center button

Open **Control Center → Add a Control → Shortcut**, tap **Choose**, and select **Run NodeUI Workflow With Prompt**. Tap the new control to enter a prompt, then submit the popup. NodeUI performs the request in the background. iOS may ask permission the first time you run a shortcut or use the local network.

This uses Apple's documented [Shortcut control](https://support.apple.com/guide/shortcuts/apd06a9201d4/ios) and [Ask for Input dialog](https://support.apple.com/guide/shortcuts/apd68b5c9161/ios).

## Receive the image

Expand **Your workflow image is ready** for **Copy Image** and **Save to Photos**. You can also open NodeUI later and use **Execution history → Shared workflows** on that server. The first image in a batch is delivered to the phone; ComfyUI keeps the full batch.

The phone needs access to the server to submit and download the result. iOS controls background delivery timing. Reopen NodeUI after force-quitting it or if a result needs recovery after losing access to the server. Comfy Cloud is not supported by this companion-based action.

## Use workflow output in the shortcut

To receive media inside Shortcuts, append these actions after **Run NodeUI Workflow With Prompt** or **Run NodeUI Workflow With Prompt And Images**:

1. **Receive NodeUI Workflow Output**: set **Job ID** to the result of the NodeUI run action. Leave **Server** empty to use that run’s server automatically.
2. **Quick Look**, **Save to Photo Album**, or **Save File**: use the receiver’s returned files as input.

The receiver waits for that job to complete successfully, then downloads images and videos from its output nodes, preserving batch order within each node and returning duplicate file references once. When **Save Image** and **Return Image to NodeUI** save the same image batch, the receiver returns the named Save Image files once. Separate image outputs and videos remain included. This includes videos reported as image or GIF output by ComfyUI video nodes. A single image is returned as a list containing one file; multiple images and mixed image/video outputs use the same list. Files keep their original formats and filenames. The existing notification still delivers the first image.

Expand the receiver using the **blue arrow beside Job ID** to set **Wait up to (seconds)**, from **1 to 3600 seconds**, with **600 seconds (10 minutes)** as the default for new actions. For a long Qwen or other image-edit workflow, choose **3600 seconds (1 hour)**. Existing shortcuts retain their saved setting, including the previous 60-second default; installing an update does not change that saved value.

If this wait expires, run the receiver again with the same job ID, or increase the wait. Receiving output never submits a second workflow. On **iOS 27 and later**, the updated receiver requests extended background execution while waiting and downloading files. Its waiting progress reports elapsed time within your selected wait, rather than a generation percentage; downloading reports transferred bytes. On iOS 26, the ordinary system background-action limit still applies. iOS can still end a shortcut; the job continues on the server and its output can be received later with the same job ID. The configured wait is a maximum, not a guarantee of background runtime.

For a job started in NodeUI or ComfyUI outside these Shortcuts actions, enter its job ID and select its saved self-hosted **Server** in the receiver. This also supports video-only runs without a Return Image to NodeUI node. A video must be saved by an output node such as Save Video or Video Combine; a preview frame does not create a video file. Missing or cancelled jobs, failed runs, and successful runs without image/video files report an error. The server and its history/output files must remain reachable. Comfy Cloud is outside this action’s scope.
