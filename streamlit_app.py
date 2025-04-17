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

st.set_page_config(
    page_title="Image Insight Explorer",
    page_icon="📷",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS for UI
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

# AWS configuration
def get_aws_credentials():
    # For local development, you might want to use environment variables or AWS profiles
    # In production, EC2 instance roles should be used
    # This is a simplified example - in production, proper credential handling is essential
    return {
        "aws_access_key_id": st.secrets.get("AWS_ACCESS_KEY_ID", ""),
        "aws_secret_access_key": st.secrets.get("AWS_SECRET_ACCESS_KEY", ""),
        "region_name": st.secrets.get("AWS_REGION", "us-east-1")
    }

# Initialize AWS clients
@st.cache_resource
def get_s3_client():
    credentials = get_aws_credentials()
    return boto3.client('s3', **credentials)

# S3 bucket names (should match AWS infrastructure)
RAW_BUCKET = "image-analyzer-raw-uploads"
PROCESSED_BUCKET = "image-analyzer-processed"
ANALYSIS_BUCKET = "image-analyzer-results"

# Helper functions for S3 operations
def upload_to_s3(file_bytes, filename, bucket):
    s3_client = get_s3_client()
    try:
        s3_client.put_object(
            Bucket=bucket,
            Key=filename,
            Body=file_bytes
        )
        return True
    except Exception as e:
        st.error(f"Error uploading to S3: {e}")
        return False

def get_analysis_results(user_id):
    s3_client = get_s3_client()
    try:
        response = s3_client.get_object(
            Bucket=ANALYSIS_BUCKET,
            Key=f"{user_id}/analysis_summary.json"
        )
        analysis_data = json.loads(response['Body'].read().decode('utf-8'))
        return analysis_data
    except Exception as e:
        st.warning("Analysis results not available yet. Processing may still be in progress.")
        return None

# app layout
def main():
    # Header 
    st.title("Photos Wrapped (temp title bc idk)")
    st.markdown("Look at your photos through a diff lens!")
    
    # Generate a unique user ID for this session if not already present
    if 'user_id' not in st.session_state:
        st.session_state.user_id = str(uuid.uuid4())
    
    # Sidebar for user controls and info
    with st.sidebar:
        st.image("https://via.placeholder.com/150x150.png?text=Image+Analyzer", width=150)
        st.title("Upload & Analyze")
        st.write("Upload up to 50 images to discover insights about your collection.")
        
        # Help section
        with st.expander("ℹ️ How it works"):
            st.markdown("""
            **This app analyzes your photos to reveal:**
            - Emotional mood patterns
            - Common objects and scenes
            - Your favorite color palette
            - Time spent in nature
            - Photo-taking patterns by time of day
            
            Your images are processed securely and automatically deleted after analysis.
            """)
    
    # Main tabs
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
                            for i, file in enumerate(uploaded_files):
                                # Create a unique filename with user_id prefix
                                file_extension = os.path.splitext(file.name)[1]
                                unique_filename = f"{st.session_state.user_id}/{uuid.uuid4()}{file_extension}"
                                
                                # Upload to S3
                                success = upload_to_s3(file.getvalue(), unique_filename, RAW_BUCKET)
                                
                                # Update progress
                                progress = (i + 1) / len(uploaded_files)
                                progress_bar.progress(progress)
                                
                                # Brief pause to show progress and not overwhelm S3
                                time.sleep(0.1)
                            
                            st.success("Images uploaded successfully! Your analysis will be ready in a moment.")
                            st.session_state.uploaded = True
                            
                            # Simulate waiting for Lambda processing
                            with st.spinner("Analyzing images..."):
                                # In a real app, we would poll for completion
                                # Here we just simulate the wait time
                                time.sleep(3)
                            
                            # Automatic switch to analysis tab
                            st.session_state.active_tab = "analysis"
                            st.experimental_rerun()
        
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
        # Check if user should be on this tab
        if 'uploaded' in st.session_state and st.session_state.uploaded:
            st.header("Your Image Collection Insights")
            
            # Try to get analysis results
            # In a real app, we'd poll S3 until results are available
            # For demo purposes, we'll generate mock results if not found
            analysis_data = get_analysis_results(st.session_state.user_id)
            
            # If no results yet, generate mock data
            if not analysis_data:
                # Mock data for demonstration
                analysis_data = {
                    "mood_analysis": {
                        "joyful": 35,
                        "serene": 25,
                        "energetic": 20,
                        "melancholic": 15,
                        "dramatic": 5
                    },
                    "common_objects": {
                        "people": 28,
                        "nature": 22,
                        "buildings": 15,
                        "animals": 12,
                        "food": 8,
                        "vehicles": 7,
                        "technology": 5,
                        "art": 3
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
            
            # Display results in a dashboard layout
            col1, col2 = st.columns(2)
            
            with col1:
                # Mood Analysis
                st.subheader("📊 Emotional Mood Analysis")
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
                
                # Most Common Objects
                st.subheader("🔍 Most Common Elements")
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
            
            with col2:
                # Color Palette
                st.subheader("🎨 Your Color Palette")
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
            
            # Additional insights and export options
            st.subheader("🔮 Key Insights")
            
            # Generate some insights based on the data
            dominant_mood = max(analysis_data["mood_analysis"].items(), key=lambda x: x[1])[0]
            dominant_object = max(analysis_data["common_objects"].items(), key=lambda x: x[1])[0]
            favorite_time = max(analysis_data["time_distribution"].items(), key=lambda x: x[1])[0]
            
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
            st.info("Please upload images in the Upload tab to see analysis results.")

# Run the app
if __name__ == "__main__":
    main()
