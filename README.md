# Custom Telephony Voice Agent

A real-time telephony voice agent built with Python, FastAPI, Twilio Media Streams, Deepgram (STT/TTS), and Groq (LLM). This project demonstrates how to connect a phone call via Twilio, stream audio in real-time, use Deepgram for accurate Speech-to-Text and natural Text-to-Speech, and integrate a fast Large Language Model like Groq for conversational AI, all orchestrated with FastAPI and WebSockets.

## Resources

*   **Detailed Blog Post:** [Transforming Voice Interactions: A Guide to Building a Telephony Bot with Twilio and WebSockets](https://medium.com/@mohammed97ashraf/transforming-voice-interactions-a-guide-to-building-a-telephony-bot-with-twilio-and-websockets-25bbdf513536)
*   **Demo Video:** [https://youtube.com/shorts/ifn6zj0YtF8](https://youtube.com/shorts/ifn6zj0YtF8)

## Prerequisites

Before you begin, ensure you have the following:

1.  **Python 3.7+:** Installed on your system.
2.  **Twilio Account:** With a phone number capable of receiving voice calls and configured for webhooks.
3.  **Deepgram Account:** Obtain an API key for STT and TTS.
4.  **Groq Account:** Obtain an API key for the LLM.
5.  **`uvicorn`:** An ASGI server to run the FastAPI application.
6.  **`ngrok` (Recommended for Local Testing):** A tool to expose your local server to the internet, necessary for Twilio to connect to your development environment.

## Setup

1.  **Clone the Repository:**
    ```bash
    git clone https://github.com/mohammed97ashraf/Custom-Telephony-Voice-Agent.git
    cd Custom-Telephony-Voice-Agent
    ```

2.  **Create a Virtual Environment and Sync Dependencies using:**
    ```bash
    uv init
    ```

3.  **Install Dependencies:**

    ```bash
    uv sync
    ```

4.  **Set Environment Variables:**
    Create a file named `.env` in the root directory of the project. Add your API keys:
    ```dotenv
    GROQ_API_KEY=YOUR_GROQ_API_KEY
    DEEPGRAM_API_KEY=YOUR_DEEPGRAM_API_KEY
    ```
    Replace `YOUR_GROQ_API_KEY` and `YOUR_DEEPGRAM_API_KEY` with your actual keys. 

## Running the Application
Assuming your main application code is in a file named `app.py` in the root directory:

1.  **Start the FastAPI Server using `uvicorn`:**
    ```bash
    cd src
    uv run app.py
    ```
    You should see output indicating the server is running, typically at `http://127.0.0.1:8000`.

2.  **Expose Your Local Server to the Internet using `ngrok`:**
    Open a new terminal window and run `ngrok` for the port your server is running on (e.g., 8000):
    ```bash
    ngrok start --all --confog ngrok.yml
    ```
    `ngrok` will provide you with public HTTPS URLs (e.g., `https://abcdef123456.ngrok.io`). Note down the **HTTPS** URL.

## Twilio Configuration

1.  **Log in to your Twilio Console.**
2.  **Navigate to Phone Numbers > Manage > Active numbers.**
3.  **Click on the phone number** you want to use for the voice agent.
4.  Scroll down to the **Voice & Fax** section.
5.  Under "A CALL COMES IN", select **Webhook**.
6.  In the text field next to "Webhook", paste the **HTTPS ngrok URL** you got in the previous step, followed by `/voice`.
    *   Example: `https://abcdef123456.ngrok.io/voice`
7.  Ensure the method is set to **HTTP POST**.
8.  **Save** the changes.

Now you should be able to call your Twilio number and interact with your AI voice agent!

## How it Works (Briefly)

1.  Twilio calls your `/voice` webhook, which responds with TwiML instructing Twilio to stream audio to your `/ws` WebSocket endpoint.
2.  Your app receives audio from Twilio via WebSocket and sends it to Deepgram STT via another WebSocket.
3.  Deepgram transcribes the audio and sends back text.
4.  Your app sends the text to Groq (LLM) to generate a response.
5.  Groq sends back the response text.
6.  Your app sends the text to Deepgram Speak (TTS) via a third WebSocket.
7.  Deepgram Speak synthesizes audio and streams it back to your app.
8.  Your app receives the TTS audio and sends it back to Twilio via the original WebSocket connection in the correct format.
9.  Twilio plays the audio to the caller.
10. Interruption handling allows the bot to stop speaking if the caller interrupts.

## Contributing

Feel free to fork the repository, open issues, or submit pull requests.

## License

MIT License

Copyright (c) 2025 Mohammed Ashraf

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
