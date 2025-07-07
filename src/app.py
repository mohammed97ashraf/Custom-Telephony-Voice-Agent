import asyncio
import os
import json
import base64
from dotenv import load_dotenv

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState # Keep for Twilio WebSocket state checks

from deepgram import (
    DeepgramClient,
    LiveTranscriptionEvents,
    LiveOptions,
    SpeakWSOptions, # Use SpeakWSOptions for WebSocket
    SpeakWebSocketEvents
)
from groq import Groq

# Load environment variables
load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")

deepgram_client = DeepgramClient(DEEPGRAM_API_KEY)
groq_client = Groq(api_key=GROQ_API_KEY)

app = FastAPI()

interrupt_event = asyncio.Event()
conversation_history = []
# ---  Variable to store the Twilio stream SID ---
twilio_stream_sid = None

# ---  Variable to hold the current TTS task ---
current_tts_task = None


# Get response from Groq
async def get_groq_response(user_message: str):
    global conversation_history
    conversation_history.append({"role": "user", "content": user_message})

    messages = [
        {"role": "system", "content": "You are a helpful and concise voice assistant. Keep your responses brief and to the point for a phone call."},
    ] + conversation_history[-10:]

    print(f"[LLM] Calling Groq with history: {messages}")
    try:
        stream = groq_client.chat.completions.create(
            messages=messages,
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            stream=True,
        )

        full_response_text = ""
        print("[LLM] Receiving stream from Groq...")
        # --- CORRECTED: Use regular 'for' loop for synchronous stream ---
        for chunk in stream:
        # --- END CORRECTED ---
            if chunk.choices[0].delta.content:
                text_chunk = chunk.choices[0].delta.content
                full_response_text += text_chunk
                
        conversation_history.append({"role": "assistant", "content": full_response_text})
        print(f"[LLM] Full response received from Groq: {full_response_text}")
        # ---  Yield the full response text after receiving it all ---
        yield full_response_text
        print("[LLM] Yielding full response text.")
        

    except Exception as e:
        print(f"[LLM] Error getting response from Groq: {type(e).__name__}: {e}")
        yield "Sorry, I couldn't get a response right now."


# Stream TTS audio to websocket using Deepgram Speak WebSocket
async def stream_tts_audio(text_iterator, websocket: WebSocket):
    global interrupt_event
    print("[TTS] >>> Entering stream_tts_audio function <<<") 
    print("[TTS] Starting audio stream.")

    dg_speak_connection = None
   

    try:
        speak_options = SpeakWSOptions(
            model="aura-2-janus-en", 
            encoding="mulaw", # Set encoding to mulaw for Twilio compatibility
            sample_rate=8000, 
        )

        print("[TTS] Creating Deepgram Speak WebSocket connection...") 
        dg_speak_connection = deepgram_client.speak.asyncwebsocket.v("1")
        print(f"[TTS] Deepgram Speak connection object created: {dg_speak_connection}") 


        # --- Define Speak connection event handlers ---
        async def on_speak_open(self, *args, **kwargs):
            print("[Speak WS] Opened")

        async def on_speak_close(self, *args, **kwargs):
            print("[Speak WS] Closed")
            # Signal the speak_closed_event when the connection closes
            if 'speak_closed_event' in locals() or 'speak_closed_event' in globals(): # Check if the event exists
                 speak_closed_event.set()


        async def on_speak_error(self, error, **kwargs):
            print(f"[Speak WS] Error: {error}")
            # If there's a Speak error, signal interruption to stop the process
            interrupt_event.set()
            if dg_speak_connection:
                 asyncio.create_task(dg_speak_connection.finish())


        # --- CORRECTED: Encode audio and send as JSON to Twilio ---
        async def on_speak_audio(self, data, **kwargs):
            global twilio_stream_sid # Access the global stream SID

            # This handler receives audio chunks from Deepgram Speak (raw bytes)
            print(f"[Speak WS] Received {len(data)} bytes of audio from Deepgram Speak.")

            # Check for interruption *before* sending audio
            if interrupt_event.is_set():
                print("[Speak WS] Interrupted during audio stream. Signaling Speak connection to finish.")
                # Signal the Speak connection to finish immediately
                if dg_speak_connection:
                    asyncio.create_task(dg_speak_connection.finish()) # Finish the connection in a task
                return # Stop processing this chunk and any subsequent ones

            # Send audio bytes back to the Twilio WebSocket
            if websocket.client_state == WebSocketState.CONNECTED:
                if twilio_stream_sid: # Ensure we have the stream SID
                    try:
                        # --- CORRECTED: Encode audio data and wrap in Twilio Media Stream JSON format ---
                        encoded_audio = base64.b64encode(data).decode("utf-8")
                        twilio_media_message = {
                            "event": "media",
                            "streamSid": twilio_stream_sid, # Include the stream SID
                            "media": {
                                "payload": encoded_audio
                            }
                        }
                        print(f"[Speak WS] Sending {len(data)} bytes (encoded) to Twilio WS.")
                        await websocket.send_text(json.dumps(twilio_media_message))
                        # --- END CORRECTION ---
                    except Exception as e:
                        print(f"[Speak WS] Error sending audio to Twilio WS: {e}")
                        # If sending fails, we should probably stop the whole process
                        # Setting interrupt event might signal the main loop to finish
                        interrupt_event.set() # Signal interruption
                        # Also signal the Speak connection to finish
                        if dg_speak_connection:
                             asyncio.create_task(dg_speak_connection.finish())
                else:
                    print("[Speak WS] Twilio stream SID not available, cannot send audio.")
                    # If stream SID is missing, signal interruption
                    interrupt_event.set()
                    if dg_speak_connection:
                         asyncio.create_task(dg_speak_connection.finish())
            else:
                print("[Speak WS] WebSocket not connected during TTS streaming. Stopping.")
                # If websocket closes, stop everything
                interrupt_event.set() # Signal interruption
                if dg_speak_connection:
                     asyncio.create_task(dg_speak_connection.finish())
        # --- END CORRECTION ---

        # Register Speak event handlers
        dg_speak_connection.on(SpeakWebSocketEvents.Open, on_speak_open)
        dg_speak_connection.on(SpeakWebSocketEvents.Close, on_speak_close)
        dg_speak_connection.on(SpeakWebSocketEvents.Error, on_speak_error)
        dg_speak_connection.on(SpeakWebSocketEvents.AudioData, on_speak_audio) # Use SpeakWebSocketEvents.AudioData


        print("[TTS] Starting Deepgram Speak WebSocket connection...") 
        if not await dg_speak_connection.start(speak_options):
             print("[TTS] Failed to start Deepgram Speak connection.")
             return # Exit if connection fails
        print("[TTS] Deepgram Speak connection started.") 

        # --- CORRECTED: Collect full text and send at once ---
        full_text_response = ""
        print("[TTS] Collecting full text response from iterator...")
        async for text_chunk in text_iterator:
            full_text_response += text_chunk
            print(f"[TTS] Collected text chunk: '{full_text_response.strip()}'") 

        if not full_text_response.strip():
            print("[TTS] No text received from LLM for TTS.")
            # Signal the Speak connection to finish if no text was received
            if dg_speak_connection:
                 await dg_speak_connection.finish()
            return # Exit the function

        print(f"[TTS] Sending full text response to Speak WS: '{full_text_response.strip()}'")
        await dg_speak_connection.send(full_text_response)
        # --- END CORRECTED ---



        # ---  Wait for the Speak connection to finish after sending text ---
        # This ensures all audio is received before the function exits
        print("[TTS] Waiting for Deepgram Speak connection to finish...")
        # We can wait for the connection to close, which happens after all audio is sent
        # Or wait for a specific event if the SDK provides one for end of audio stream
        # For now, let's rely on the connection closing after finish() is called implicitly or explicitly
        # A simple sleep is a less robust alternative, but can work for testing
        # await asyncio.sleep(5) # Example: wait for 5 seconds (not ideal)

        # A better approach is to wait for the connection to close, which is signaled by the on_speak_close handler
        # We can use an event to signal when the close handler is called
        speak_closed_event = asyncio.Event()
        # Re-bind the on_speak_close handler to set the event
        dg_speak_connection.on(SpeakWebSocketEvents.Close, lambda self, *args, **kwargs: speak_closed_event.set())


        # --- CORRECTED: Wrap coroutines in asyncio.create_task() ---
        print("[TTS] Waiting for Speak connection to close or interrupt...")
        # Wait for either the Speak connection to close OR the interrupt event to be set
        await asyncio.wait([asyncio.create_task(speak_closed_event.wait()), asyncio.create_task(interrupt_event.wait())], return_when=asyncio.FIRST_COMPLETED)
        print("[TTS] Waiting for Speak connection finished (closed or interrupted).")
        # --- END CORRECTED ---


        # After sending all text (or if interrupted), finish the Speak connection
        # This signals Deepgram to stop processing and close the connection
        # --- CORRECTED: Remove .state check ---
        if dg_speak_connection: # Check if the object exists
             print("[TTS] Signaling Deepgram Speak connection to finish (cleanup)...") 
             await dg_speak_connection.finish()
             print("[TTS] Signaled Deepgram Speak connection to finish (cleanup).") 
        # --- END CORRECTED ---

        # Wait briefly for the connection to close and final audio to be sent
        # This is a heuristic; a more robust way would be to wait for the on_speak_close event
        # or use a method like wait_until_finished() if the SDK provides one.
        # await asyncio.sleep(0.5) # Give a little time for final audio/close events - Removed in favor of waiting for close event
        print("[TTS] Exiting stream_tts_audio after waiting for Speak connection.")


    except asyncio.CancelledError:
        print("[TTS] stream_tts_audio task cancelled.")
    except WebSocketDisconnect:
        print("[TTS] WebSocket disconnected during TTS process.")
    except Exception as e:
        print(f"[TTS] An unexpected error occurred during TTS process: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc() # Add traceback for better debugging

    finally:
        print("[TTS] Entering finally block for stream_tts_audio.") 
        # Ensure tasks and connections are cleaned up
        # The text_sender_task is removed, so no need to cancel it here

        # --- CORRECTED: Remove .state check ---
        if dg_speak_connection: # Check if the object exists
            try:
                print("[TTS] Ensuring Deepgram Speak connection is finished in finally block...") 
                await dg_speak_connection.finish()
                print("[TTS] Ensured Deepgram Speak connection is finished in finally.") 
            except Exception as e:
                 print(f"[TTS] Error finishing Deepgram Speak connection in finally: {type(e).__name__}: {e}")
        # --- END CORRECTED ---

        print("[TTS] Finished stream_tts_audio function.") 


# Twilio voice webhook
@app.post("/voice")
async def twilio_voice(request: Request):
    # Note: Twilio requires a public URL. If running locally, use ngrok or similar.
    # The URL should be accessible from the internet.
    # Example: ngrok http 8000
    # Then use the ngrok https://... URL in your Twilio webhook settings.
    # The /ws path will automatically be available under that same domain.
    # request.url.hostname might be 'localhost' if running locally without ngrok
    # For production, ensure your server's public domain is used.
    # If using ngrok, the hostname will be the ngrok URL.
    public_url = request.url.hostname
    ws_url = f'wss://{public_url}/ws'
    print(f"Twilio connecting to WebSocket at: {ws_url}")

    response_twiml = f"""
    <Response>
        <Connect>
            <Stream url="{ws_url}"/>
        </Connect>
    </Response>
    """
    return Response(content=response_twiml, media_type="application/xml")

# Websocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("WebSocket connection established with Twilio.")

    global interrupt_event
    global conversation_history
    global twilio_stream_sid # Access the global stream SID
    global current_tts_task # Access the global TTS task variable

    conversation_history = []
    interrupt_event.clear()
    twilio_stream_sid = None # Reset stream SID for a new connection
    current_tts_task = None # Reset TTS task for a new connection


    dg_connection = None # Deepgram STT connection
    audio_sender_task = None # Task to send audio from Twilio WS to Deepgram STT

    try:
        # --- Deepgram STT Setup ---
        dg_connection = deepgram_client.listen.asyncwebsocket.v("1")

        # Deepgram STT events handlers
        async def on_message(self, result, **kwargs):
            global current_tts_task # Access the global TTS task variable
            global twilio_stream_sid # Access the global stream SID

            transcript = result.channel.alternatives[0].transcript
            if len(transcript) > 0:
                print(f"[STT] {transcript} (is_final: {result.is_final})")

                is_final_deepgram = result.is_final and result.speech_final

                # Check for potential interruption on interim results
                if not is_final_deepgram and len(transcript.strip()) > 3 and not interrupt_event.is_set():
                    print(f"[STT] Potential interruption detected by Deepgram: '{transcript}'")
                    interrupt_event.set() # Signal interruption
                    # ---  Send Twilio 'clear' message on interruption ---
                    if websocket.client_state == WebSocketState.CONNECTED and twilio_stream_sid:
                        print("[STT] Sending Twilio 'clear' message due to interruption.")
                        clear_message = {
                            "event": "clear",
                            "streamSid": twilio_stream_sid
                        }
                        try:
                            await websocket.send_text(json.dumps(clear_message))
                            print("[STT] Twilio 'clear' message sent.")
                        except Exception as e:
                            print(f"[STT] Error sending Twilio 'clear' message: {e}")
                    
                    # ---  Cancel the current TTS task if it exists ---
                    if current_tts_task and not current_tts_task.done():
                        print("[STT] Cancelling current TTS task due to interruption.")
                        current_tts_task.cancel()
                    


                # Process the final transcript
                if is_final_deepgram:
                    print(f"[STT] Final transcript received: {transcript}")
                    # Clear interrupt event before processing the new turn
                    interrupt_event.clear()
                    # Create a task to process the user's turn (LLM + TTS)
                    print("[STT] Creating task to process user turn...")
                    # --- CORRECTED: Store the new TTS task ---
                    current_tts_task = asyncio.create_task(process_user_turn(transcript, websocket))
                    # --- END CORRECTED ---

        async def on_stt_open(self, open_payload, **kwargs):
            print(f"[STT WS] Connection Opened: {open_payload}")

        async def on_stt_error(self, error, **kwargs):
            print(f"[STT WS] Error: {error}")

        async def on_stt_close(self, **kwargs):
            print(f"[STT WS] Connection Closed.")

        # --- CORRECTED: Make handlers accept *args and **kwargs ---
        async def on_speech_started(self, *args, **kwargs):
            print(f"[STT WS] Speech Started: args={args}, kwargs={kwargs}")

        async def on_utterance_end(self, *args, **kwargs):
            print(f"[STT WS] Utterance End: args={args}, kwargs={kwargs}")
        # --- END CORRECTION ---

        # Bind Deepgram STT events
        dg_connection.on(LiveTranscriptionEvents.Open, on_stt_open)
        dg_connection.on(LiveTranscriptionEvents.Transcript, on_message)
        dg_connection.on(LiveTranscriptionEvents.Error, on_stt_error)
        dg_connection.on(LiveTranscriptionEvents.Close, on_stt_close)
        dg_connection.on(LiveTranscriptionEvents.SpeechStarted, on_speech_started)
        dg_connection.on(LiveTranscriptionEvents.UtteranceEnd, on_utterance_end)

        # Start Deepgram STT connection
        # --- Match Twilio's mu-law format for STT ---
        options = LiveOptions(
            model="nova-2",
            language="en-US",
            encoding="mulaw", 
            sample_rate=8000, 
            channels=1,
            punctuate=True,
            interim_results=True,
            endpointing=100,
            vad_events=True,
        )
        # --- End STT Options ---

        print("[STT WS] Starting Deepgram STT connection...")
        if not await dg_connection.start(options):
            print("[STT WS] Failed to connect to Deepgram STT")
            return # Exit if connection fails

        print("[STT WS] Deepgram STT connection started.")


        # --- Task to handle incoming Twilio MediaStream data and send to Deepgram STT ---
        async def _send_audio_to_deepgram():
            global twilio_stream_sid # Access the global stream SID
            print("[WebSocket] Starting audio sender task to Deepgram STT.")
            try:
                while True:
                    # Receive data from Twilio WebSocket
                    incoming = await websocket.receive()
                    # print(f"[WebSocket] Received message type: {list(incoming.keys())}") 

                    if 'text' in incoming:
                        payload = json.loads(incoming['text'])

                        # Check for 'media' event which contains audio data
                        if payload.get("event") == "media":
                            media_payload = payload["media"]["payload"]
                            audio_data = base64.b64decode(media_payload)
                            # Send audio data to Deepgram STT
                            if dg_connection: # Check if the object exists
                                try:
                                    # --- CORRECTED: Await the send() method ---
                                    await dg_connection.send(audio_data)
                                except Exception as e:
                                    # Handle potential errors if sending fails (e.g., connection closed)
                                    print(f"[WebSocket] Error sending audio to Deepgram STT: {e}")
                                    # If sending fails, signal interruption to stop processing
                                    interrupt_event.set()
                                    # Break the loop as the connection is likely bad
                                    break
                            else:
                                print("[WebSocket] Deepgram STT connection not initialized, dropping audio.")
                        elif payload.get("event") == "start":
                            print(f"[Twilio Event] Call started: {payload}")
                            # ---  Store the stream SID ---
                            if 'streamSid' in payload:
                                twilio_stream_sid = payload['streamSid']
                                print(f"[WebSocket] Stored Twilio stream SID: {twilio_stream_sid}")
                            else:
                                print("[WebSocket] Twilio stream SID not found in payload.")
                        elif payload.get("event") == "connected":
                             print(f"[Twilio Event] Received connected event: {payload}")
                        elif payload.get("event") == "stop":
                             print(f"[Twilio Event] Call stopped: {payload}")
                             # When Twilio stops, we should also stop the Deepgram connection and the WebSocket
                             break # Exit the loop
                         # --- Handle the 'mark' event from Twilio ---
                        elif payload.get("event") == "mark":
                             print(f"[Twilio Event] Received mark event: {payload}")
                        else:
                            print(f"[Twilio Event] Received unknown event: {payload.get('event')}")

                    elif 'bytes' in incoming:
                        print("[WebSocket] Unexpected binary message received. Ignoring.")

            except WebSocketDisconnect:
                print("[WebSocket] Twilio WebSocket disconnected (send_audio_to_deepgram task).")
            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"[WebSocket] Error in _send_audio_to_deepgram: {type(e).__name__}: {e}")
            finally:
                print("[WebSocket] Audio sender task finished.")
                # Ensure Deepgram STT connection is finished when the WebSocket closes or loop breaks
                if dg_connection: # Check if the object exists
                    try:
                        await dg_connection.finish()
                        print("[STT WS] Deepgram STT connection finished.")
                    except Exception as e:
                        print(f"[STT WS] Error finishing Deepgram STT connection in finally: {type(e).__name__}: {e}")
        # --- End audio sender task ---


        # --- Function to process user turns (LLM + TTS) ---
        async def process_user_turn(user_input: str, ws: WebSocket):
            global current_tts_task # Access the global TTS task variable
            if not user_input.strip():
                print("[LLM] User input was empty, skipping Groq call.")
                return

            print(f"[LLM] Processing user turn: '{user_input}'")
            try:
                # Get streaming response from Groq
                groq_text_chunks = get_groq_response(user_input)
                # Stream the Groq response text to Deepgram TTS and send audio back
                print("[LLM] Calling stream_tts_audio...")
                # --- CORRECTED: Pass the websocket object to stream_tts_audio ---
                await stream_tts_audio(groq_text_chunks, ws)
                # --- END CORRECTED ---
                print("[LLM] Finished processing user turn.")
            except asyncio.CancelledError:
                 print("[LLM] User turn processing cancelled (interrupted).")
            except Exception as e:
                print(f"[LLM] Error processing user turn: {type(e).__name__}: {e}")
                import traceback
                traceback.print_exc()
                # Optionally, speak an error message
                # await stream_tts_audio(iter(["Sorry, I encountered an error."]), ws)
            finally:
                 # ---  Clear the current_tts_task variable when the task finishes or is cancelled ---
                 current_tts_task = None
                 print("[LLM] current_tts_task cleared.")
                 


        # Start the task that listens for incoming audio from Twilio and sends to Deepgram STT
        audio_sender_task = asyncio.create_task(_send_audio_to_deepgram())
        print("[WebSocket] Audio sender task created.")

        # Keep the WebSocket connection open by awaiting the audio task
        # The audio_sender_task will exit when the Twilio WebSocket disconnects or sends a 'stop' event
        await audio_sender_task
        print("[WebSocket] Audio sender task completed.")

    except WebSocketDisconnect:
        print("[WebSocket] Main WebSocket loop detected disconnect.")
    except Exception as e:
        print(f"[WebSocket] Error in websocket_endpoint: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("[WebSocket] Entering finally block for websocket_endpoint.")
        # Ensure tasks are cancelled
        if audio_sender_task and not audio_sender_task.done():
            print("[WebSocket] Cancelling audio sender task in finally.") 
            audio_sender_task.cancel()
            try:
                await audio_sender_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                print(f"[WebSocket] Error during audio sender task cleanup: {type(e).__name__}: {e}")

        # Ensure Deepgram STT connection is finished
        if dg_connection: # Check if the object exists
            try:
                print("[STT WS] Ensuring Deepgram STT connection is finished in finally.") 
                await dg_connection.finish()
                print("[STT WS] Ensured Deepgram STT connection is finished in finally.") 
            except Exception as e:
                 print(f"[STT WS] Error finishing Deepgram STT connection in finally: {type(e).__name__}: {e}")

        # Ensure the Twilio WebSocket is closed
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close()
            print("[WebSocket] Twilio WebSocket closed.")

if __name__ == "__main__":
    import uvicorn
    # Run the FastAPI app with Uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)