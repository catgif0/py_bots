# Use an official Python runtime as a parent image
FROM python:3.8-slim

# Set the working directory in the container
WORKDIR /usr/src/app

# Copy the current directory contents into the container at /usr/src/app
COPY . .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Install tweepy
RUN pip install tweepy

# Install Gunicorn
RUN pip install gunicorn

# Expose port 8080 to the outside world
EXPOSE 8080

# Define environment variables for Flask
ENV FLASK_APP=signal_bot.py
ENV FLASK_ENV=production

# Run the Gunicorn server to serve the Flask application
CMD ["gunicorn", "-b", "0.0.0.0:8080", "signal_bot:app"]
