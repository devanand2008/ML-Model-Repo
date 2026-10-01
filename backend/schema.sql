-- PostgreSQL schema generated from backend/database.py

CREATE TABLE ai_models (
	id SERIAL NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	model_type VARCHAR(60) NOT NULL, 
	filename VARCHAR(255) NOT NULL, 
	description TEXT, 
	version VARCHAR(40), 
	is_active BOOLEAN, 
	is_default BOOLEAN, 
	confidence_threshold FLOAT, 
	class_names TEXT, 
	dataset_info TEXT, 
	metrics TEXT, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	updated_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id)
)

;
CREATE INDEX ix_ai_models_id ON ai_models (id);

CREATE TABLE datasets (
	id SERIAL NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	dataset_type VARCHAR(60) NOT NULL, 
	description TEXT, 
	num_images INTEGER, 
	num_labels INTEGER, 
	class_names TEXT, 
	split_info TEXT, 
	yaml_path VARCHAR(255), 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id)
)

;
CREATE INDEX ix_datasets_id ON datasets (id);

CREATE TABLE users (
	id SERIAL NOT NULL, 
	username VARCHAR(120) NOT NULL, 
	role VARCHAR(30), 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (username)
)

;

CREATE TABLE analyses (
	id SERIAL NOT NULL, 
	user_id INTEGER, 
	analyzer_type VARCHAR(60) NOT NULL, 
	input_filename VARCHAR(255), 
	input_type VARCHAR(20), 
	output_filename VARCHAR(255), 
	model_id INTEGER, 
	confidence_threshold FLOAT, 
	total_objects INTEGER, 
	image_width INTEGER, 
	image_height INTEGER, 
	processing_time FLOAT, 
	results TEXT, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(model_id) REFERENCES ai_models (id)
)

;
CREATE INDEX ix_analyses_id ON analyses (id);

CREATE TABLE model_versions (
	id SERIAL NOT NULL, 
	model_id INTEGER NOT NULL, 
	version VARCHAR(40) NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	filename VARCHAR(255) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(model_id) REFERENCES ai_models (id)
)

;

CREATE TABLE detections (
	id SERIAL NOT NULL, 
	analysis_id INTEGER NOT NULL, 
	class_name VARCHAR(120) NOT NULL, 
	confidence FLOAT NOT NULL, 
	bbox_x FLOAT, 
	bbox_y FLOAT, 
	bbox_w FLOAT, 
	bbox_h FLOAT, 
	track_id INTEGER, 
	frame_number INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(analysis_id) REFERENCES analyses (id)
)

;
CREATE INDEX ix_detections_id ON detections (id);
