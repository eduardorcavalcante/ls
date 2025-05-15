# Use a Python base image (you can choose a specific version)
FROM python:3.9-slim-buster

# Set the working directory inside the container
WORKDIR /app

# Copy the application code into the container
COPY . /app

# Install any dependencies (e.g., Flask, boto3)
RUN pip install --no-cache-dir -r requirements.txt

# Make port 80 available to the world outside this container
EXPOSE 80

# Define the command to run the application
CMD ["python", "main.py"]