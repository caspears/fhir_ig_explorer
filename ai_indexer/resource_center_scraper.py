import os
import requests
from markdownify import markdownify as md
from bs4 import BeautifulSoup


RESOUREC_CENTER_PAGES = {'about': 'https://www.cdc.gov/nhsn/fhirportal/about.html', 'fhir-ready': 'https://www.cdc.gov/nhsn/fhirportal/dqm/fhir-ready.html', 'faq': 'https://www.cdc.gov/nhsn/fhirportal/faqs.html'}
# Define the path to your HTML file


for key, value in RESOUREC_CENTER_PAGES.items():
    response = requests.get(value)

# Check if the request was successful
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, 'html.parser')

        # Find all divs with the specific class
        divs = soup.find_all('div', class_='syndicate')

        heads = soup.find_all('head')
        #print(head)
        new_html = "<html><body>"

        # Shouldn't have more than one head, but hey.
        for head in heads:
            new_html = new_html + str(head) #print(div.text) # or div.get_text()

        for div in divs:
            new_html = new_html + str(div) #print(div.text) # or div.get_text()
        
        new_html = new_html + "</body></html>"

        
        with open(key + ".html", "w", encoding="utf-8") as file:
            file.write(new_html)
        # 2. Convert the HTML to Markdown
        markdown_content = md(new_html, heading_style="ATX")

        with open(key + ".md", 'w', encoding='utf-8') as f:
            f.write(markdown_content)




# input_file = 'test.html'

# # 1. Read the HTML file
# with open(input_file, 'r', encoding='utf-8') as f:
#     html_content = f.read()

# # 2. Convert the HTML to Markdown
# markdown_content = md(html_content, heading_style="ATX")

# # 3. Create the new file name (replaces .html with .md)
# output_file = os.path.splitext(input_file)[0] + '.md'

# # 4. Save to a new .md file
# with open(output_file, 'w', encoding='utf-8') as f:
#     f.write(markdown_content)

# print(f"Successfully converted {input_file} to {output_file}")