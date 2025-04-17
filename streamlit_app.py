import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import plotly.express as px
import plotly.graph_objects as go
from PIL import Image, ExifTags
import boto3
import io
import os
import json
import time
from datetime import datetime
import uuid
from io import BytesIO
import tempfile

# Set page configuration with a clean aesthetic
st.set_page_config(
    page_title="Image Insight Explorer",
    page_icon="📷",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for aesthetic UI
st.markdown("""
<style>
    /* Main page styling */
    .main {
        background-color: #f8f9fa;
        color: #333;
        font-family: 'Helvetica Neue', sans-serif;
    }
    
    /* Headers */
    h1, h2, h3 {
        font-family: 'Helvetica Neue', sans-serif;
        color: #1e1e1e;
        font-weight: 600;
    }
    
    /* Custom container for cards */
    .css-1r6slb0 {
        background-color: white;
        border-radius: 10px;
        padding: 20px;
        box-shadow: 0 4px 8px rgba(0,0,0,0.05);
        margin-bottom: 20px;
    }
    
    /* Streamlit elements styling */
    .stButton>button {
        background-color: #5046e4;
        color: white;
        border-radius: 8px;
        font-weight: 500;
        border: none;
        padding: 0.5rem 1rem;
        transition: all 0.3s ease;
    }
    
    .stButton>button:hover {
        background-color: #3731b3;
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
    }
    
    /* Custom metrics */
    .metric-card {
        background-color: white;
        border-radius: 8px;
        padding: 16px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        text-align: center;
    }
    
    .metric-value {
        font-size: 28px;
        font-weight: 700;
        color: #5046e4;
        margin-bottom: 4px;
    }
    
    .metric-label {
        font-size: 14px;
        color: #666;
    }
    
    /* File uploader styling */
    .stFileUploader {
        padding: 10px;
        border-radius: 8px;
        background-color: #f0f2f6;
    }
    
    /* Progress bar styling */
    .stProgress > div > div > div {
        background-color: #5046e4;
    }
</style>
""", unsafe_allow_html=True)

# AWS configuration - use environment variables or secrets manager
def get_aws_credentials():
    # For local development, credentials can be set in the environment or using st.secrets
    # In production on EC2, instance roles should be used
    return {
        "aws_access_key_id": st.secrets.get("AWS_ACCESS_KEY_ID", os.environ.get("AWS_ACCESS_KEY_ID", "")),
        "aws_secret_access_key": st.secrets.get("AWS_SECRET_ACCESS_KEY", os.environ.get("AWS_SECRET_ACCESS_KEY", "")),
        "region_name": st.secrets.get("AWS_REGION", os.environ.get("AWS_REGION", "us-east-1"))
    }

# Initialize AWS clients
@st.cache_resource
def get_s3_client():
    credentials = get_aws_credentials()
    return boto3.client('s3', **credentials)

# S3 bucket names - match with your infrastructure (s3_upload.py and preprocess.py)
RAW_BUCKET = "landingpg1014"  # Matches your s3_upload.py bucket
PROCESSED_BUCKET = "processingdata4300"  # Matches your preprocess.py OUTPUT_BUCKET
META_PREFIX = "metadata/"  # Matches your preprocess.py META_PREFIX
UPLOADS_PREFIX = "uploads/"  # Matches your preprocess.py UPLOADS_PREFIX

# Function to upload files to S3 landing bucket
def upload_to_s3(file_bytes, filename, user_id="ruchira"):
    s3_client = get_s3_client()
    try:
        # Create key in the format matching your s3_upload.py
        key = f"{UPLOADS_PREFIX}{filename}"
        
        # Use metadata matching your upload script
        content_type = "image/jpeg" if filename.lower().endswith((".jpg", ".jpeg")) else "image/png"
        
        s3_client.put_object(
            Bucket=RAW_BUCKET,
            Key=key,
            Body=file_bytes,
            ContentType=content_type,
            Metadata={
                "uploaded-by": user_id,
                "project": "image-upload-test"
            }
        )
        return True, key
    except Exception as e:
        st.error(f"Error uploading to S3: {e}")
        return False, None

# Function to check if analysis results are available and retrieve them
def get_analysis_results(user_id):
    """Get analysis summary for a user by aggregating individual image metadata"""
    s3_client = get_s3_client()
    
    try:
        # List all metadata files for this user
        response = s3_client.list_objects_v2(
            Bucket=PROCESSED_BUCKET,
            Prefix=f"{META_PREFIX}{user_id}/"
        )
        
        # If no metadata files found yet, return None
        if 'Contents' not in response:
            return None
            
        # Collect metadata from all processed images
        all_metadata = []
        for item in response.get('Contents', []):
            try:
                obj = s3_client.get_object(
                    Bucket=PROCESSED_BUCKET,
                    Key=item['Key']
                )
                metadata = json.loads(obj['Body'].read().decode('utf-8'))
                all_metadata.append(metadata)
            except Exception as e:
                st.warning(f"Error reading metadata file {item['Key']}: {e}")
                
        # If no metadata was successfully loaded, return None
        if not all_metadata:
            return None
            
        # Aggregate the data to create summary statistics
        return aggregate_analysis_data(all_metadata)
    except Exception as e:
        st.warning(f"Error retrieving analysis results: {e}")
        return None

# Function to aggregate metadata from multiple images into summary statistics
def aggregate_analysis_data(all_metadata):
    """Transform individual image metadata into aggregated statistics"""
    if not all_metadata:
        return None
        
    # Initialize counters and collectors
    mood_counts = {}
    object_counts = {}
    time_counts = {"morning": 0, "afternoon": 0, "evening": 0, "night": 0}
    color_samples = []
    nature_scores = []
    
    # Process each image metadata
    for metadata in all_metadata:
        # Aggregate mood data
        if 'mood' in metadata and 'primary_mood' in metadata['mood']:
            primary_mood = metadata['mood']['primary_mood']
            mood_counts[primary_mood] = mood_counts.get(primary_mood, 0) + 1
        
        # Aggregate object data
        if 'objects' in metadata and 'objects' in metadata['objects']:
            for obj in metadata['objects']['objects']:
                obj_name = obj['name'].lower()
                object_counts[obj_name] = object_counts.get(obj_name, 0) + 1
        
        # Aggregate time data
        if 'hour_of_day' in metadata:
            hour = metadata['hour_of_day']
            if 5 <= hour < 12:
                time_counts["morning"] += 1
            elif 12 <= hour < 17:
                time_counts["afternoon"] += 1
            elif 17 <= hour < 21:
                time_counts["evening"] += 1
            else:
                time_counts["night"] += 1
        
        # Collect color data
        if 'colors' in metadata and metadata['colors']:
            for color in metadata['colors']:
                color_samples.append({
                    'hex': color['hex'],
                    'frequency': color['frequency']
                })
        
        # Collect nature scores
        if 'nature' in metadata and 'nature_ratio' in metadata['nature']:
            nature_scores.append(metadata['nature']['nature_ratio'])
    
    # Calculate aggregated color palette
    color_palette = aggregate_colors(color_samples)
    
    # Calculate nature percentage
    avg_nature_score = sum(nature_scores) / len(nature_scores) if nature_scores else 0
    nature_percentage = int(avg_nature_score * 100)
    
    # Convert counts to percentages
    total_images = len(all_metadata)
    
    mood_analysis = {k: int((v / total_images) * 100) for k, v in mood_counts.items()}
    
    # Ensure all time periods have values
    total_time_images = sum(time_counts.values())
    time_distribution = {k: int((v / total_time_images) * 100) if total_time_images > 0 else 0 
                         for k, v in time_counts.items()}
    
    # Get top objects (up to 10)
    sorted_objects = sorted(object_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    common_objects = {k: v for k, v in sorted_objects}
    
    # Create aggregated analysis data
    analysis_data = {
        "mood_analysis": mood_analysis,
        "common_objects": common_objects,
        "color_palette": color_palette,
        "nature_percentage": nature_percentage,
        "time_distribution": time_distribution
    }
    
    return analysis_data

# Helper function to aggregate colors from multiple images
def aggregate_colors(color_samples, num_colors=6):
    if not color_samples:
        return []
        
    # Simple approach: count occurrences of similar colors
    # In a real app, you could use clustering to find the most representative colors
    color_counter = {}
    for color in color_samples:
        hex_color = color['hex']
        if hex_color in color_counter:
            color_counter[hex_color] += color['frequency']
        else:
            color_counter[hex_color] = color['frequency']
    
    # Get the top colors
    sorted_colors = sorted(color_counter.items(), key=lambda x: x[1], reverse=True)[:num_colors]
    
    # Calculate percentages
    total = sum(count for _, count in sorted_colors)
    color_palette = []
    
    for hex_color, count in sorted_colors:
        percentage = int((count / total) * 100) if total > 0 else 0
        color_palette.append({
            "color": hex_color,
            "percentage": percentage
        })
    
    return color_palette

# Function to check if analysis is complete
def check_processing_status(user_id):
    """Check if all uploaded images have been processed"""
    s3_client = get_s3_client()
    
    try:
        # Count raw uploads for this user
        raw_response = s3_client.list_objects_v2(
            Bucket=RAW_BUCKET,
            Prefix=f"{user_id}/"
        )
        raw_count = len(raw_response.get('Contents', []))
        
        # Count processed metadata files
        processed_response = s3_client.list_objects_v2(
            Bucket=PROCESSED_BUCKET,
            Prefix=f"{META_PREFIX}{user_id}/"
        )
        processed_count = len(processed_response.get('Contents', []))
        
        # If no uploads found, return False
        if raw_count == 0:
            return False
            
        # If all images have been processed, return True
        if processed_count >= raw_count:
            return True
            
        # Otherwise, return the progress percentage
        return processed_count / raw_count
    except Exception as e:
        st.warning(f"Error checking processing status: {e}")
        return False

# Main app layout
def main():
    # Header section
    st.title("✨ Image Insight Explorer")
    st.markdown("Discover the stories your images tell through data analysis")
    
    # Generate a unique user ID for this session if not already present
    if 'user_id' not in st.session_state:
        st.session_state.user_id = "ruchira"  # Default user ID matching your s3_upload.py
    
    # Track upload status
    if 'uploaded' not in st.session_state:
        st.session_state.uploaded = False
    
    # Sidebar for user controls and info
    with st.sidebar:
        st.image("https://via.placeholder.com/150x150.png?text=Photo+Insights", width=150)
        st.title("Upload & Analyze")
        st.write("Upload up to 50 images to discover insights about your collection.")
        
        # Help expander
        with st.expander("ℹ️ How it works"):
            st.markdown("""
            **This app analyzes your photos to reveal:**
            - Emotional mood patterns
            - Common objects and scenes
            - Your favorite color palette
            - Time spent in nature
            - Photo-taking patterns by time of day
            
            Your images are processed securely in AWS using:
            - S3 for storage
            - Lambda for image analysis
            - Rekognition for object detection
            
            The analysis pipeline extracts insights about your images and displays them in this dashboard.
            """)
    
    # Main content tabs
    tab1, tab2 = st.tabs(["📤 Upload Images", "📊 View Analysis"])
    
    # Upload tab
    with tab1:
        st.header("Upload Your Images")
        
        col1, col2 = st.columns([3, 2])
        
        with col1:
            uploaded_files = st.file_uploader(
                "Select up to 50 images to analyze", 
                type=['jpg', 'jpeg', 'png'], 
                accept_multiple_files=True
            )
            
            if uploaded_files:
                num_files = len(uploaded_files)
                if num_files > 50:
                    st.warning("Please select a maximum of 50 images.")
                else:
                    st.write(f"{num_files} image{'s' if num_files > 1 else ''} selected")
                    
                    # Display upload button
                    if st.button("Process Images", key="process_btn"):
                        with st.spinner("Uploading and processing your images..."):
                            # Progress bar
                            progress_bar = st.progress(0)
                            
                            # Upload each file to S3 raw bucket
                            uploaded_keys = []
                            for i, file in enumerate(uploaded_files):
                                # Upload to S3
                                success, key = upload_to_s3(
                                    file.getvalue(),
                                    file.name,
                                    st.session_state.user_id
                                )
                                
                                if success and key:
                                    uploaded_keys.append(key)
                                
                                # Update progress
                                progress = (i + 1) / len(uploaded_files)
                                progress_bar.progress(progress)
                                
                                # Brief pause to show progress and not overwhelm S3
                                time.sleep(0.1)
                            
                            if uploaded_keys:
                                st.success(f"Successfully uploaded {len(uploaded_keys)} images to S3.")
                                st.session_state.uploaded = True
                                
                                # Wait for Lambda processing (in a real app, we'd poll for completion)
                                with st.spinner("Waiting for image processing to complete..."):
                                    # Simulate waiting for Lambda processing
                                    for i in range(10):
                                        time.sleep(0.5)
                                        status = check_processing_status(st.session_state.user_id)
                                        if isinstance(status, float):
                                            progress_bar.progress(status)
                                        elif status:
                                            progress_bar.progress(1.0)
                                            break
                                
                                # Switch to analysis tab
                                st.success("Image processing complete! View your analysis in the Analysis tab.")
                            else:
                                st.error("Failed to upload images. Please try again.")
        
        with col2:
            st.markdown("""
            <div style="background-color: #f8f9fa; padding: 20px; border-radius: 10px; margin-top: 20px;">
                <h4>📝 Tips for best results</h4>
                <ul>
                    <li>Choose a diverse set of images for more interesting insights</li>
                    <li>Include photos from different times of day</li>
                    <li>Select images with EXIF data intact for time analysis</li>
                    <li>Analysis works best with clear, well-lit photos</li>
                </ul>
            </div>
            """, unsafe_allow_html=True)
    
    # Analysis tab
    with tab2:
        st.header("Your Image Collection Insights")
        
        # Check if analysis results are available
        if st.session_state.uploaded:
            # Real implementation: Try to get analysis results from S3
            analysis_data = get_analysis_results(st.session_state.user_id)
            
            if analysis_data:
                # Display results in a dashboard layout
                col1, col2 = st.columns(2)
                
                with col1:
                    # Mood Analysis
                    st.subheader("📊 Emotional Mood Analysis")
                    if analysis_data["mood_analysis"]:
                        mood_data = pd.DataFrame({
                            'Mood': list(analysis_data["mood_analysis"].keys()),
                            'Percentage': list(analysis_data["mood_analysis"].values())
                        })
                        
                        fig = px.pie(
                            mood_data, 
                            values='Percentage', 
                            names='Mood',
                            color_discrete_sequence=px.colors.qualitative.Pastel,
                            hole=0.4
                        )
                        fig.update_layout(
                            margin=dict(t=0, b=0, l=0, r=0),
                            legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5)
                        )
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info("Mood analysis data not available.")
                    
                    # Most Common Objects
                    st.subheader("🔍 Most Common Elements")
                    if analysis_data["common_objects"]:
                        objects_data = pd.DataFrame({
                            'Object': list(analysis_data["common_objects"].keys()),
                            'Count': list(analysis_data["common_objects"].values())
                        }).sort_values('Count', ascending=False)
                        
                        fig = px.bar(
                            objects_data,
                            y='Object',
                            x='Count',
                            orientation='h',
                            color='Count',
                            color_continuous_scale='Viridis'
                        )
                        fig.update_layout(margin=dict(t=10, b=0, l=0, r=0))
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info("Object detection data not available.")
                
                with col2:
                    # Color Palette
                    st.subheader("🎨 Your Color Palette")
                    if analysis_data["color_palette"]:
                        colors = [item["color"] for item in analysis_data["color_palette"]]
                        percentages = [item["percentage"] for item in analysis_data["color_palette"]]
                        
                        # Display color swatches
                        color_cols = st.columns(len(colors))
                        for i, (col, color, pct) in enumerate(zip(color_cols, colors, percentages)):
                            col.markdown(
                                f"""
                                <div style="background-color: {color}; height: 100px; border-radius: 5px; margin-bottom: 5px;"></div>
                                <p style="text-align: center; font-size: 14px;">{pct}%</p>
                                """, 
                                unsafe_allow_html=True
                            )
                    else:
                        st.info("Color palette data not available.")
                    
                    # Nature vs Urban
                    st.subheader("🌿 Nature Content")
                    
                    nature_pct = analysis_data["nature_percentage"]
                    urban_pct = 100 - nature_pct
                    
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.markdown(
                            f"""
                            <div class="metric-card">
                                <div class="metric-value">{nature_pct}%</div>
                                <div class="metric-label">Nature Content</div>
                            </div>
                            """, 
                            unsafe_allow_html=True
                        )
                    
                    with col2:
                        st.markdown(
                            f"""
                            <div class="metric-card">
                                <div class="metric-value">{urban_pct}%</div>
                                <div class="metric-label">Urban/Indoor Content</div>
                            </div>
                            """, 
                            unsafe_allow_html=True
                        )
                    
                    # Time Distribution
                    st.subheader("⏰ Time of Day Distribution")
                    if analysis_data["time_distribution"]:
                        time_data = pd.DataFrame({
                            'Time': list(analysis_data["time_distribution"].keys()),
                            'Percentage': list(analysis_data["time_distribution"].values())
                        })
                        
                        # Custom order for time of day
                        time_order = ["morning", "afternoon", "evening", "night"]
                        time_data['Time'] = pd.Categorical(time_data['Time'], categories=time_order, ordered=True)
                        time_data = time_data.sort_values('Time')
                        
                        fig = px.line(
                            time_data, 
                            x='Time', 
                            y='Percentage',
                            markers=True,
                            line_shape='spline',
                            color_discrete_sequence=['#5046e4']
                        )
                        fig.update_traces(marker_size=10)
                        fig.update_layout(margin=dict(t=10, b=0, l=0, r=0))
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info("Time distribution data not available.")
                
                # Additional insights and export options
                st.subheader("🔮 Key Insights")
                
                # Generate insights if data is available
                if analysis_data["mood_analysis"]:
                    dominant_mood = max(analysis_data["mood_analysis"].items(), key=lambda x: x[1])[0]
                else:
                    dominant_mood = "Unknown"
                
                if analysis_data["common_objects"]:
                    dominant_object = max(analysis_data["common_objects"].items(), key=lambda x: x[1])[0]
                else:
                    dominant_object = "Unknown"
                
                if analysis_data["time_distribution"]:
                    favorite_time = max(analysis_data["time_distribution"].items(), key=lambda x: x[1])[0]
                else:
                    favorite_time = "Unknown"
                
                insight_cols = st.columns(3)
                
                with insight_cols[0]:
                    st.markdown(
                        f"""
                        <div class="metric-card" style="height: 120px;">
                            <h4>Dominant Mood</h4>
                            <div class="metric-value" style="font-size: 22px;">{dominant_mood.title()}</div>
                            <div class="metric-label">Your photos mostly convey {dominant_mood} emotions</div>
                        </div>
                        """, 
                        unsafe_allow_html=True
                    )
                
                with insight_cols[1]:
                    st.markdown(
                        f"""
                        <div class="metric-card" style="height: 120px;">
                            <h4>Favorite Subject</h4>
                            <div class="metric-value" style="font-size: 22px;">{dominant_object.title()}</div>
                            <div class="metric-label">Most common element in your collection</div>
                        </div>
                        """, 
                        unsafe_allow_html=True
                    )
                
                with insight_cols[2]:
                    st.markdown(
                        f"""
                        <div class="metric-card" style="height: 120px;">
                            <h4>Preferred Time</h4>
                            <div class="metric-value" style="font-size: 22px;">{favorite_time.title()}</div>
                            <div class="metric-label">When you capture most of your photos</div>
                        </div>
                        """, 
                        unsafe_allow_html=True
                    )
                
                # Export options
                st.subheader("📁 Export Options")
                export_cols = st.columns([1, 1, 2])
                
                with export_cols[0]:
                    st.download_button(
                        label="Download PDF Report",
                        data=b"Sample PDF Report",  # In a real app, generate a real PDF
                        file_name="image_insights_report.pdf",
                        mime="application/pdf"
                    )
                
                with export_cols[1]:
                    st.download_button(
                        label="Export JSON Data",
                        data=json.dumps(analysis_data, indent=2),
                        file_name="image_analysis_data.json",
                        mime="application/json"
                    )
            else:
                # Display a waiting message or offer to process mock data for demo purposes
                st.info("Waiting for image analysis to complete... This may take a few minutes.")
                st.progress(0.6)  # Show progress indicator
                
                if st.button("Generate Demo Results (for testing)"):
                    # Generate mock data for demonstration
                    analysis_data = {
                        "mood_analysis": {
                            "calm": 35,
                            "happy": 25,
                            "energetic": 20,
                            "melancholic": 15,
                            "neutral": 5
                        },
                        "common_objects": {
                            "Person": 28,
                            "Nature": 22,
                            "Building": 15,
                            "Animal": 12,
                            "Food": 8,
                            "Vehicle": 7,
                            "Technology": 5,
                            "Art": 3
                        },
                        "color_palette": [
                            {"color": "#4287f5", "percentage": 25},
                            {"color": "#42f5aa", "percentage": 22},
                            {"color": "#f5da42", "percentage": 18},
                            {"color": "#f55f42", "percentage": 15},
                            {"color": "#8742f5", "percentage": 12},
                            {"color": "#f542f2", "percentage": 8}
                        ],
                        "nature_percentage": 37,
                        "time_distribution": {
                            "morning": 15,
                            "afternoon": 42,
                            "evening": 32,
                            "night": 11
                        }
                    }
                    st.session_state.demo_data = analysis_data
                    st.experimental_rerun()
        else:
            # Prompt user to upload images first
            st.info("Please upload images in the Upload tab to see analysis results.")
            
            # Option to use mock data for testing
            if st.button("Try with Sample Data"):
                st.session_state.uploaded = True
                st.experimental_rerun()

# Run the app
if __name__ == "__main__":
    main()
